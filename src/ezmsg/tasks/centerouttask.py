import typing
import asyncio
import datetime
import random

import numpy as np
import panel as pn
import ezmsg.core as ez

from .task import (
    Task,
    TaskSettings,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState
)
from dataclasses import dataclass
from .ssvep.stimulus import Fixation
from ezmsg.sigproc.sampler import SampleTriggerMessage

@dataclass
class CenterOutRxnMessage(SampleTriggerMessage):
    trial_onset: datetime = None
    trial_end: datetime = None
    rxn_time: datetime = None
    trial_duration: datetime.timedelta = None

    stimulus_location: str = None

class CenterOutTaskImplementationState(TaskImplementationState):
    stim_presentation_grid: pn.layout.GridBox
    task_area: pn.layout.Card

    trials_per_location: pn.widgets.IntInput
    trial_duration: pn.widgets.FloatInput
    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    intertrial_min_dur: pn.widgets.TextInput
    intertrial_max_dur: pn.widgets.TextInput
    task_controls: pn.layout.WidgetBox

    locations: typing.List[str]

    rxn_time: datetime
    buttonpress_event: asyncio.Event



class CenterOutTaskImplementation(TaskImplementation):
    STATE: CenterOutTaskImplementationState

    # INPUT_CLASS = ez.InputStream(typing.Optional[str])
    # OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])

    OUTPUT_CENTEROUT_RXN = ez.OutputStream(typing.Optional[CenterOutRxnMessage])

    @property
    def slug(self) -> str:
        ''' Short-name used to id recorded files '''
        return 'CENTEROUT'
    
    @property
    def title(self) -> str:
        ''' Title of task used in header of page '''
        return 'Center Out Reaction Task'


    
    async def initialize(self) -> None:
        await super().initialize()
        self.STATE.locations = ['up', 'left', 'right', 'down']
        self.STATE.ntrials = 1
        self.STATE.rxn_time = 0

        sw = dict(sizing_mode = 'stretch_width')
        stimulus_kwargs = dict(size = 500)
        self.STATE.buttonpress_event = asyncio.Event()

        ''' set up settings card '''
        self.STATE.trials_per_location = pn.widgets.IntInput(name = 'Trials per-location', value = 10, start = 1, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.trial_duration = pn.widgets.FloatInput(name = 'Trial dur. (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

        ''' set up stimulus card '''
        # 3x3 grid w/ [1,1] being fixation
        ''' row, col
        [0, 0] [0, 1] [0, 2]
        [1, 0] [1, 1] [1, 2]
        [2, 0] [2, 1] [2, 2]
        '''
        '''
        grid_components = [pn.pane.HTML(sizing_mode='stretch_width') for i in range(9)]
        grid_components[4] = Fixation(**stimulus_kwargs)
        self.STATE.stimulus_map = {}
        j = 0
        for i in np.arange(1,9,2):
            grid_components[i] = pn.widgets.Button(visible=False, height=600, width=600)
            self.STATE.stimulus_map[self.STATE.locations[j]] = i
            j += 1

        self.STATE.stim_presentation_grid = pn.layout.GridBox(*grid_components, nrows=3, ncols=3)
        '''
        self.STATE.stim_presentation_grid = pn.GridSpec(width=600*3, height=600*3)
        for i in np.arange(3):
            for j in np.arange(3):
                self.STATE.stim_presentation_grid[i,j] = pn.Spacer(styles=dict(background='#808080'))
        # up
        self.STATE.stim_presentation_grid[0, 1] = pn.widgets.Button(button_type='default')
        # left
        self.STATE.stim_presentation_grid[1, 0] = pn.widgets.Button(button_type='default')
        # right
        self.STATE.stim_presentation_grid[1, 2] = pn.widgets.Button(button_type='default')
        # down
        self.STATE.stim_presentation_grid[2, 1] = pn.widgets.Button(button_type='default')

        # fixation
        self.STATE.stim_presentation_grid[1,1] = pn.Column(pn.layout.VSpacer(),
                                                           pn.Row(pn.layout.HSpacer(width=300), pn.indicators.Number(value=10, format='+'), pn.layout.HSpacer(width=300)),
                                                           pn.layout.VSpacer())

        self.STATE.task_area = pn.Card(
            pn.Row(self.STATE.stim_presentation_grid, align='center'),
            styles = {'background': '#808080'},
            hide_header = True,
            sizing_mode = 'stretch_both'
        )

        @pn.depends(
                self.STATE.trials_per_location, 
                self.STATE.trial_duration,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            trials_per_location: int,
            trial_dur: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            n_trials = len(self.STATE.locations) * trials_per_location
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + trial_dur) * n_trials
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{len(self.STATE.locations)} locations, {n_trials} trial(s), ~{run_dur}'
        
        # This is done here to kick the calculation for run_calc
        self.STATE.trials_per_location.param.update(value=10)

        self.STATE.task_controls = pn.WidgetBox(
            pn.Row(
                self.STATE.trials_per_location,
                self.STATE.trial_duration,
            ),
            pn.Row(
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
            ), 
            pn.Row(
                self.STATE.intertrial_min_dur, 
                self.STATE.intertrial_max_dur, 
            ),
            sizing_mode = 'stretch_both'
        )


    async def task_implementation(self) -> typing.AsyncIterator[SampleTriggerMessage | None]:
        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            trials_per_location: int = self.STATE.trials_per_location.value
            trial_dur: float = self.STATE.trial_duration.value # type: ignore
            iti_min: float = self.STATE.intertrial_min_dur.value # type: ignore
            iti_max: float = self.STATE.intertrial_max_dur.value # type: ignore
            pre_run_duration: float = self.STATE.pre_run_duration.value # type: ignore
            post_run_duration: float = self.STATE.post_run_duration.value # type: ignore

            # create trial order (blockwise randomized)
            trials: typing.List[str] = []
            for _ in range(trials_per_location):
                random.shuffle(self.STATE.locations)
                trials += self.STATE.locations
            
            self.STATE.progress.max = len(trials)
            self.STATE.progress.value = 0
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            ''' pre run '''
            self.STATE.status.value = 'Pre Run'
            await asyncio.sleep(pre_run_duration)

            for trial_idx, trial_location in enumerate(trials):
                ''' ITI '''
                trial_id = f'Trial {trial_idx + 1} / {len(trials)}'

                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                await asyncio.sleep(iti)

                ''' Stim Presentation '''
                # make correct button visible/change color
                button = pn.widgets.Button(button_type='primary')
                def on_buttonpress(event):
                    # save rxn time
                    self.STATE.rxn_time = datetime.datetime.now()
                    self.STATE.buttonpress_event.set()
                pn.bind(on_buttonpress, button, watch=True)
                match trial_location:
                    case 'up':
                        self.STATE.stim_presentation_grid[0, 1] = button
                    case 'left':
                        self.STATE.stim_presentation_grid[1, 0] = button
                    case 'right':
                        self.STATE.stim_presentation_grid[1, 2] = button
                    case 'down':
                        self.STATE.stim_presentation_grid[2, 1] = button
                onset_time = datetime.datetime.now()
                self.STATE.status.value = f'{trial_id}: Action ({trial_location})'

                # await reaction, save response time
                # if timeout, response time = trial time
                try:
                    await asyncio.wait_for(self.STATE.buttonpress_event.wait(), trial_dur)
                    trialdur_timedelta = self.STATE.rxn_time - onset_time
                    trialdur_seconds = trialdur_timedelta.total_seconds()
                    # yield message
                    yield CenterOutRxnMessage(
                        period = (-trialdur_seconds, 0.0), 
                        value = trial_location,
                        trial_onset=onset_time,
                        trial_end=self.STATE.rxn_time,
                        rxn_time=self.STATE.rxn_time,
                        trial_duration=trialdur_seconds,
                        stimulus_location=trial_location
                   )
                    # unset event
                    self.STATE.buttonpress_event.clear()
                except:
                    print('timeout')
                    now = datetime.datetime.now()
                    # yield message
                    yield CenterOutRxnMessage(
                        period = (-trial_dur, 0.0), 
                        value = trial_location,
                        trial_onset=onset_time,
                        trial_end=now,
                        rxn_time=now,
                        trial_duration=trial_dur,
                        stimulus_location=trial_location
                   )
                # stop stimulus
                match trial_location:
                    case 'up':
                        self.STATE.stim_presentation_grid[0, 1] = pn.widgets.Button(button_type='default')
                    case 'left':
                        self.STATE.stim_presentation_grid[1, 0] = pn.widgets.Button(button_type='default')
                    case 'right':
                        self.STATE.stim_presentation_grid[1, 2] = pn.widgets.Button(button_type='default')
                    case 'down':
                        self.STATE.stim_presentation_grid[2, 1] = pn.widgets.Button(button_type='default')

                # update progress
                self.STATE.progress.value = trial_idx + 1

            ''' post run '''
            self.STATE.status.value = 'Post Run'
            await asyncio.sleep(post_run_duration)

            raise TaskComplete


        finally:
            self.STATE.task_controls.disabled = False
    
    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls,
                title = 'Center Out Reaction Task'
            )
        ])
        return sidebar
    

class CenterOutTask(Task):
    TASK: CenterOutTaskImplementation = CenterOutTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network())

