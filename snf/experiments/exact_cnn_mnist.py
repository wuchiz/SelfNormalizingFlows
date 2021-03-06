import torch
from torch import optim
from torch.optim.lr_scheduler import StepLR

from snf.layers import Dequantization, Normalization
from snf.layers.distributions.uniform import UniformDistribution
from snf.layers.flowsequential import FlowSequential
from snf.layers.selfnorm import SelfNormConv
from snf.layers.activations import SmoothLeakyRelu, SplineActivation, LearnableLeakyRelu, Identity
from snf.layers.squeeze import Squeeze
from snf.layers.transforms import LogitTransform
from snf.train.losses import NegativeGaussianLoss
from snf.train.experiment import Experiment
from snf.datasets.mnist import load_data

activations = {
    'SLR':lambda size: SmoothLeakyRelu(alpha=0.3),
    'LLR': lambda size: LearnableLeakyRelu(),
    'Spline': lambda size: SplineActivation(size, tail_bound=10, individual_weights=True),
    'SELU': lambda size: SELU(alpha=1.6733, lamb=1.0507)
}

def create_model(num_layers=100, sym_recon_grad=False, 
                 activation='Spline', recon_loss_weight=1.0,
                 num_blocks=3):
    block_size = int(num_layers / num_blocks)
    act = activations[activation]

    alpha = 1e-6
    layers = [
        Dequantization(UniformDistribution(size=(1, 28, 28))),
        Normalization(translation=0, scale=256),
        Normalization(translation=-alpha, scale=1 / (1 - 2 * alpha)),
        LogitTransform(),
    ]

    current_size = (1, 28, 28)

    for b in range(num_blocks):
        for l in range(block_size):
            layers.append(SelfNormConv(current_size[0],current_size[0], (3, 3),
                                       bias=True, stride=1, padding=1,
                                       sym_recon_grad=sym_recon_grad, 
                                       recon_loss_weight=recon_loss_weight))
            
            if not (b == num_blocks - 1 and l == block_size - 1):
                # Dont place activation at end of last block
                layers.append(act(current_size))

        if not (b == num_blocks - 1):
            # Only squeeze between blocks
            layers.append(Squeeze())
            current_size = (current_size[0]*4, 
                            current_size[1]//2,
                            current_size[2]//2)

    return FlowSequential(NegativeGaussianLoss(size=current_size), 
                         *layers)


def main():
    config = {
        'name': '9L Conv Exact Spline MNIST (lr1e-3)',
        'eval_epochs': 1,
        'sample_epochs': 1,
        'log_interval': 100,
        'lr': 1e-3,
        'num_layers': 9,
        'batch_size': 100,
        'verbose': False,
        'modified_grad': False,
        'add_recon_grad': False,
        'sym_recon_grad': False,
        'activation': 'Spline',
        'recon_loss_weight': 1.0,
        'log_timing': True
    }

    train_loader, val_loader, test_loader = load_data(batch_size=config['batch_size'])

    model = create_model(num_layers=config['num_layers'], 
                         sym_recon_grad=config['sym_recon_grad'],
                         activation=config['activation'],
                         recon_loss_weight=config['recon_loss_weight']).to('cuda')

    optimizer = optim.Adam(model.parameters(), lr=config['lr'], betas=(0.9, 0.999))
    scheduler = StepLR(optimizer, step_size=1, gamma=1.0)

    experiment = Experiment(model, train_loader, val_loader, test_loader,
                            optimizer, scheduler, **config)

    experiment.run()