"""Late-fusion SCIN network, separate from Flask and its unconfigured AI adapter."""

from __future__ import annotations

import torch
from torch import nn
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small


class MultimodalDermatologyModel(nn.Module):
    """Fuse a primary RGB image with already encoded patient metadata.

    Args:
        metadata_dim: Width of the training-fitted metadata encoder output.
        num_classes: Number of diagnosis logits in the unchanged class order.
        pretrained: Load ImageNet weights for training. Set False only for
            explicit architecture tests or checkpoint reconstruction; failures
            downloading real weights are never replaced with random weights.
    """

    def __init__(self, metadata_dim: int, num_classes: int = 41, pretrained: bool = True):
        super().__init__()
        if metadata_dim < 1 or num_classes < 2:
            raise ValueError("metadata_dim must be positive and num_classes at least two.")
        self.metadata_dim = int(metadata_dim)
        self.num_classes = int(num_classes)
        self.pretrained_requested = bool(pretrained)
        weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
        backbone = mobilenet_v3_small(weights=weights)
        self.features = backbone.features
        self.avgpool = backbone.avgpool
        self.image_projection = nn.Sequential(
            nn.Linear(576, 128), nn.ReLU(), nn.Dropout(0.3)
        )
        self.metadata_branch = nn.Sequential(
            nn.Linear(self.metadata_dim, 64), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(64, 32), nn.ReLU(),
        )
        self.fusion_head = nn.Sequential(
            nn.Linear(160, 128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, self.num_classes),
        )
        self._frozen_feature_indices: tuple[int, ...] = ()

    def set_trainable_backbone_blocks(self, last_blocks: int = 0) -> None:
        """Train only the final ``last_blocks`` feature blocks, freezing the rest.

        Freezing BatchNorm running statistics matters as much as freezing its
        parameters: otherwise phase-one training silently changes the backbone.
        """
        if not isinstance(last_blocks, int) or not 0 <= last_blocks <= len(self.features):
            raise ValueError("last_blocks must identify existing CNN feature blocks.")
        cutoff = len(self.features) - last_blocks
        self._frozen_feature_indices = tuple(range(cutoff))
        for index, block in enumerate(self.features):
            block.requires_grad_(index >= cutoff)
        self.train(self.training)

    def train(self, mode: bool = True):
        """Respect frozen BatchNorm statistics when a loop calls ``model.train``."""
        super().train(mode)
        if mode:
            for index in self._frozen_feature_indices:
                self.features[index].eval()
        return self

    def forward(self, images: torch.Tensor, metadata: torch.Tensor) -> torch.Tensor:
        """Return unnormalized logits; softmax belongs only in prediction code."""
        if images.ndim != 4 or images.shape[1] != 3:
            raise ValueError("images must have shape [batch, 3, height, width].")
        if metadata.ndim != 2 or metadata.shape[1] != self.metadata_dim:
            raise ValueError(f"metadata must have shape [batch, {self.metadata_dim}].")
        if images.shape[0] != metadata.shape[0]:
            raise ValueError("Images and metadata must have the same batch size.")
        image_features = self.avgpool(self.features(images)).flatten(1)
        image_embedding = self.image_projection(image_features)
        metadata_embedding = self.metadata_branch(metadata)
        return self.fusion_head(torch.cat((image_embedding, metadata_embedding), dim=1))
