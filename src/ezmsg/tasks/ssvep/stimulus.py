import base64

import imageio
import numpy as np
import numpy.typing as npt

from PIL import Image
from typing import List
from pathlib import Path
from importlib.resources import files
from dataclasses import dataclass, field

data_files = files('ezmsg.tasks')

@dataclass(frozen = True)
class GIFStimulus:
    """
    gif is a pretty limiting format; only supports integer multiples of 10ms frame periods
    stick to reversal durations that are integer multiples of 0.01 ms > 0.02 ms
    NOTE: very few browsers support 100 fps gifs (so avoid reversal period of 0.01 ms)
    """

    duration: float = 0.08 # frame duration
    size: int = 600 # px
    _src: str = field(init = False)

    def __post_init__(self) -> None:
        stim_bytes = imageio.mimwrite(
            '<bytes>',
            ims = self.images(), 
            format = 'gif', # type: ignore
            loop = 0,
            fps = int(1.0/self.duration),
        )

        stim_b64 = base64.b64encode(stim_bytes).decode("ascii")

        # Working around frozen dataclass for image caching
        object.__setattr__(self, '_src', f'data:image/gif;base64,{stim_b64}')
    
    def images(self) -> List[npt.NDArray[np.uint8]]:
        half = self.size / 2.0
        px = (np.arange(self.size) - half) / half
        x, y = np.meshgrid(px, px)
        return self.design(x, y)

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        raise NotImplementedError
    
    def _repr_html_(self) -> str:
        return f"""<center><img src="{self._src}"/></center>"""

@dataclass(frozen=True)
class VisualMotionStimulus(GIFStimulus):
    icon_path: Path = data_files.joinpath('resources/icon.png')

    def design(self, x: npt.NDArray, y:npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        period_ms = self.duration * 1000

        # set # frames and angle increment for one full rotation
        num_frames = 25
        angle_increment = 360/num_frames
        
        # calculate duration of each frame
        duration = period_ms/num_frames

        icon = Image.open(self.icon_path)
        #icon = icon.resize((round(self.size/2), round(self.size/2)), resample=Image.BICUBIC)
        icon = icon.resize((self.size, self.size), resample=Image.BICUBIC)
        icon_center = (icon.width//2, icon.height//2)

        image = []
        for i in range(num_frames):
            angle_deg = i * angle_increment
            angle_rad = np.radians(angle_deg)

            scale_factor = abs(np.cos(angle_rad))
            scaled_width = int(icon.width * scale_factor)
            scaled_icon = icon.resize((scaled_width, icon.height), resample=Image.BICUBIC)

            background = Image.new("RGBA", (self.size, self.size), (128, 128, 128, 128))
            pos = (
                (self.size - scaled_icon.width) // 2,
                (self.size - scaled_icon.height) // 2,
            )
            background.paste(scaled_icon, pos, scaled_icon)

            image.append(np.asarray(background).astype(np.uint8))
        
        #print(image.shape)
        return image

@dataclass(frozen = True)
class RadialCheckerboard(GIFStimulus):
    angular_freq: float = 40.0 # number of checkers around circle
    radial_freq: float = 10.0 # number of checkers to center
    radial_exp: float = 0.5 # warp factor for checker length to center

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        dist = np.sqrt(x**2 + y**2) ** self.radial_exp
        angle = np.arctan2(y,x)
        image = np.sin(2 * np.pi * (self.radial_freq / 2.0) * dist)
        image *= np.cos(angle * self.angular_freq / 2.0)
        image = np.sign(image)
        image[np.where(dist > 1.0)] = 0
        scale = lambda x: (x + 1.0) * ((2**7) - 1)
        print(np.array([
            scale(image).astype(np.uint8), 
            scale(image * -1).astype(np.uint8)
        ]).shape)
        return [
            scale(image).astype(np.uint8), 
            scale(image * -1).astype(np.uint8)
        ]
    
@dataclass(frozen = True)
class Fixation(GIFStimulus):
    radius: float = 0.01 # fraction of image size

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        image = np.ones_like(x) * 2**7
        dist = np.sqrt(x**2 + y**2)
        image[np.where(dist < self.radius)] = 0
        return [image.astype(np.uint8)]

@dataclass(frozen=True)
class Indication(GIFStimulus):
    indication_path: Path = data_files.joinpath('resources/arrow.png')
    def design(self, x:npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        arrow = Image.open(self.indication_path)
        return [np.array(arrow).astype(np.uint8)]



