import torch
from torch import nn, optim
import torch.nn.functional as F
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
import json
import numpy as np

import warnings
warnings.filterwarnings("ignore")

# Every batch in the dataset shares the same affine transformation variable

def plot_image_grid(images, ncols=None, cmap="gray"):
    if not ncols:
        factors = [i for i in range(1, len(images)+1) if len(images) % i == 0]
        ncols = factors[len(factors) // 2] if len(factors) else len(images) // 4 + 1
    nrows = int(len(images) / ncols) + int(len(images) % ncols)
    imgs = [images[i] if len(images) > i else None for i in range(nrows * ncols)]
    _, axes = plt.subplots(nrows, ncols, figsize=(3*ncols, 2*nrows))
    axes = axes.flatten()[:len(imgs)]
    for img, ax in zip(imgs, axes.flatten()): 
        if np.any(img):
            if len(img.shape) > 2 and img.shape[2] == 1:
                img = img.squeeze()
            ax.imshow(img, cmap=cmap)
    plt.show()

def progress(current,total,**kwargs):
    done_token, current_token = ("=", ">")
    token_arr = []
    bar = total // 25
    token_arr.extend([done_token]*(current//bar))
    if (total-current): token_arr.extend([current_token])
    attrs = json.dumps(kwargs).replace('"',"")[1:-1]
    final = f"{current}/{total} [{''.join(token_arr)}{' '*max(0,25-current//bar)}] - {attrs}"
    print(final,end=("\r","\n\n")[current==total])

transform = transforms.Compose([
    transforms.ToTensor(),
])

PI = torch.tensor(3.14159265358979323)
batch_size = 32
num_epochs = 151
lrr = 0.1
lrt = 0.01
lrsc = 0.01
lrd = 0.0001

dataset = list(datasets.MNIST(root="MNIST_data/", transform=transform, download=True))
for i in range(len(dataset)):
    img = dataset[i][0].unsqueeze(dim=0)
    r = torch.tensor(3.)
    t = torch.tensor([0.5, 0.5])
    sc = torch.tensor(1.25)
    rot = torch.stack([torch.stack([
        torch.stack([torch.cos(r) / sc, -torch.sin(r) / sc, torch.tensor(t[0]) / sc]),
        torch.stack([torch.sin(r) / sc, torch.cos(r) / sc, torch.tensor(t[1]) / sc])
        ])])
    grid = F.affine_grid(rot, img.size(), align_corners=False)
    img = F.grid_sample(img, grid, align_corners=False)
    dataset[i] = (img, dataset[i][1])  
loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

fake_dataset = datasets.MNIST(root="MNIST_data/", transform=transform, download=True)
fake_loader = DataLoader(fake_dataset, batch_size=batch_size, shuffle=True)

fixed_noise = torch.randint(0,len(loader)-1,())


class Generator(nn.Module):
    def __init__(self):
        super().__init__()
        self.rot = torch.full((batch_size,),(0.)).requires_grad_()
        self.trans = torch.full((batch_size,2),(0.)).requires_grad_()
        self.scale = torch.full((batch_size,),(1.)).requires_grad_()
    
    def forward(self,idx):
        for _, (batch, _) in enumerate(fake_loader,idx):
            rot = torch.stack([torch.stack([
                torch.stack([torch.cos(self.rot[i]) / self.scale[i], -torch.sin(self.rot[i]) / self.scale[i], self.trans[i][0] / self.scale[i]]),
                torch.stack([torch.sin(self.rot[i]) / self.scale[i], torch.cos(self.rot[i]) / self.scale[i], self.trans[i][1] / self.scale[i]])
                ]) for i in range(batch_size)])
            grid = F.affine_grid(rot, batch.size(), align_corners=False)
            batch = F.grid_sample(batch, grid, align_corners=False)

            return batch


class Discriminator(nn.Module):
    def __init__(self):
        super().__init__()
        
        self.net = nn.Sequential(
            nn.Conv2d(1,4,kernel_size=3),
            nn.Conv2d(4,1,kernel_size=2),
            nn.Flatten(),
            nn.Linear(25*25,1),
            nn.Sigmoid()
        )
    
    def forward(self,img):
        return self.net(img)

gen = Generator()
disc = Discriminator()
criterion = nn.BCELoss()

opt_rot = optim.AdamW([gen.rot], lr=lrr, amsgrad=True, weight_decay=0.001)
opt_trans = optim.AdamW([gen.trans], lr=lrt, amsgrad=True, weight_decay=0.001)
opt_scale = optim.AdamW([gen.scale], lr=lrsc, amsgrad=True, weight_decay=0.001)
opt_disc = optim.AdamW(disc.parameters(), lr=lrd, amsgrad=True, weight_decay=0.001)

with torch.no_grad():
    plot_image_grid(next(iter(loader))[0].reshape(-1, 28, 28, 1).numpy())
    fake = gen(fixed_noise).reshape(-1, 28, 28, 1)
    plot_image_grid(fake.detach().numpy())
        
for epoch in range(num_epochs):
    print(f"Epoch {epoch+1}/{num_epochs}")
    for batch_idx, (real, _) in enumerate(loader):
        real = real.view(-1,1,28,28)
        
        # Train Discriminator: max log(D(real)) + log(1-D(G(z)))
        opt_disc.zero_grad()
        noise = torch.randint(0,len(loader)-1,())
        fake = gen(noise)
        disc_real = disc(real).view(-1)
        lossD_real = criterion(disc_real, torch.ones_like(disc_real))
        disc_fake = disc(fake).view(-1)
        lossD_fake = criterion(disc_fake, torch.zeros_like(disc_fake))
        lossD = lossD_real + lossD_fake
        lossD.backward(retain_graph=True)
        opt_disc.step()
        
        # Train Generator min log(1-D(G(z))) <--> max log(D(G(z)))
        opt_rot.zero_grad()
        opt_trans.zero_grad()
        opt_scale.zero_grad()
        
        output = disc(fake).view(-1)
        lossG = criterion(output, torch.ones_like(output))  
        lossG.backward()
        
        opt_rot.step()
        opt_trans.step()
        opt_scale.step()
        
        with torch.no_grad():
            progress(batch_idx+1,len(loader),
                     g=round(float(lossG.mean().numpy()),2),
                     d=round(float(lossD.mean().numpy()),2),
                     r=round(float(gen.rot.median().numpy()),2),
                     t=round(float(gen.trans.median().numpy()),2),
                     sc=round(float(gen.scale.median().numpy()),2))

    if epoch % 25 == 0:
        with torch.no_grad():
            fake = gen(fixed_noise).reshape(-1, 28, 28, 1)
            plot_image_grid(fake.detach().numpy())
