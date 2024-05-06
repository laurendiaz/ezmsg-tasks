import typing
import random
import asyncio
import logging
import datetime

from pathlib import Path
from ezmsg.core.collection import NetworkDefinition
from param.parameterized import Event
from dataclasses import dataclass, field

import ezmsg.core as ez
import panel as pn
import numpy as np

from ezmsg.panel.tabbedapp import Tab
from ezmsg.sigproc.sampler import SampleTriggerMessage

from ..task import (
    Task,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState
)

from .stimulus import *

@dataclass
class SSVEPSampleTriggerMessage(SampleTriggerMessage):
    expected_freq: typing.Optional[float] = None
    freqs: typing.List[float] = field(default_factory = list)

class MultiSSVEPTaskState(TaskImplementationState):
    stimuli: typing.List[pn.pane.HTML]
    stim_indications: typing.List[pn.pane.HTML]
    task_area: pn.layout.Card

    stimulus_type: pn.widgets.Select
    classes: pn.widgets.MultiChoice

    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    trials_per_class: pn.widgets.IntInput
    trial_duration: pn.widgets.FloatInput
    intertrial_min_dur: pn.widgets.FloatInput
    intertrial_max_dur: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    input_classes: asyncio.Queue[typing.Optional[typing.List[str]]]
    output_classes: asyncio.Queue[typing.Optional[typing.List[str]]]
    # input_stimtype: asyncio.Queue[typing.Optional[str]]
    # output_stimtype: asyncio.Queue[typing.Optional[str]]

    stimulus_map: typing.Dict[str, GIFStimulus]
    fixations: typing.List[Fixation]
    indications: typing.List[Indication]

    periods: typing.List[float]
    freqs: typing.List[str]

class MultiSSVEPTaskImplementation(TaskImplementation):
    STATE: MultiSSVEPTaskState

    INPUT_CLASS = ez.InputStream(typing.Optional[typing.List[str]])
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[typing.List[str]])
    # INPUT_STIMTYPE = ez.InputStream(typing.Optional[str])
    # OUTPUT_TARGET_STIMTYPE = ez.OutputStream(typing.Optional[str])

    @property
    def slug(self) -> str:
        ''' Shortname used to id recorded files '''
        return 'MULTISSVEPTASK'
    
    @property
    def title(self) -> str:
        ''' Full name of task that appears in UI '''
        return 'Multiple Steady State Visually Evoked Potentials'
    
    async def initialize(self) -> None:
        await super().initialize()
        sw = dict(sizing_mode = 'stretch_width')

        self.STATE.periods = ((np.arange(6) * 0.020) + 0.040)[::-1]
        self.STATE.periods = np.concatenate((self.STATE.periods, [1.0/7.0, 1.0/11.0, 1.0/13.0]))
        self.STATE.periods = -np.sort(-self.STATE.periods)
        self.STATE.freqs = [f'{(1.0/p):.02f} Hz' for p in self.STATE.periods]

        ''' set up SSVEP trial card '''
        self.STATE.stimulus_type = pn.widgets.Select(name='Stimulus Type', options=['Radial Checkerboard', 'Visual Motion'], **sw)
        self.STATE.classes = pn.widgets.MultiChoice(name = 'Classes', options = self.STATE.freqs, max_items = 4, **sw)

        self.STATE.trials_per_class = pn.widgets.IntInput(name = 'Trials per-class', value = 10, start = 1, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.trial_duration = pn.widgets.FloatInput(name = 'Trial dur. (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

        @pn.depends(
                self.STATE.stimulus_type,
                self.STATE.classes, 
                self.STATE.trials_per_class, 
                self.STATE.trial_duration,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            stim_type: str,
            classes: typing.List[str], 
            trials_per_class: int,
            trial_dur: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            print('updateruncalc')
            ''' set up stimuli presentation card '''
            # stimuli + fixations + indications initialization
            stimulus_kwargs = dict(size = 500)
            stim_section = pn.Row()
            stimuli = []  

            fixations = []

            indications_section = pn.Row()
            stim_indications = []
            indications = []

            for i in np.arange(len(classes)):
                stim = pn.pane.HTML(sizing_mode = 'stretch_width')
                indication = pn.pane.HTML(sizing_mode = 'stretch_width')
                if(i == 0):
                    stim_section.append(stim)

                    indications_section.append(indication)
                else:
                    stim_section.append(pn.layout.HSpacer())
                    stim_section.append(stim)

                    indications_section.append(pn.layout.HSpacer())
                    indications_section.append(indication)

                stimuli.append(stim)
                stim_indications.append(indication)

                indications.append(Indication(**stimulus_kwargs))
                fixations.append(Fixation(**stimulus_kwargs))

            self.STATE.stimuli = stimuli
            self.STATE.stim_indications = stim_indications
            self.STATE.indications = indications
            self.STATE.fixations = fixations
            
            # generate task area card
            self.STATE.task_area = pn.Card(
                pn.Column(
                    pn.layout.VSpacer(),
                    stim_section,
                    pn.layout.VSpacer(),
                    indications_section,
                    pn.layout.VSpacer(),
                    min_height = 1200
                ),
                styles = {'background': '#808080'},
                hide_header = True,
                sizing_mode = 'stretch_both'
            )

            #initialize stimuli with fixations
            for i in np.arange(len(classes)):
                self.STATE.stimuli[i].object = self.STATE.fixations[i]

            ''' create stimulus map'''
            if(stim_type == 'Radial Checkerboard'):
                self.STATE.stimulus_map = {f: RadialCheckerboard(duration = p, **stimulus_kwargs) for f, p in zip(self.STATE.freqs, self.STATE.periods)}
            elif(stim_type == 'Visual Motion'):
                self.STATE.stimulus_map = {f: VisualMotionStimulus(duration=p, **stimulus_kwargs) for f, p in zip(self.STATE.freqs, self.STATE.periods)}
        

            ''' run calculations '''
            n_trials = len(classes) * trials_per_class
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + trial_dur) * n_trials
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{len(classes)} class(es), {n_trials} trial(s), ~{run_dur}'

        # This is done here to kick the calculation for run_calc
        self.STATE.classes.param.update(value = [self.STATE.freqs[(len(self.STATE.freqs)//2)]])


        self.STATE.task_controls = pn.WidgetBox(
            self.STATE.classes,
            self.STATE.stimulus_type,
            pn.Row(
                self.STATE.trials_per_class,
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

        self.STATE.output_classes = asyncio.Queue()
        self.STATE.input_classes = asyncio.Queue()

    @ez.subscriber(INPUT_CLASS)
    async def on_class_input(self, msg: typing.Optional[typing.List[str]]) -> None:
        self.STATE.input_classes.put_nowait(msg)
    
    # @ez.subscriber(INPUT_STIMTYPE)
    # async def on_stimtype_input(self, msg: typing.Optional[str]) -> None:
    #     self.STATE.input_stimtype.put_nowait(msg)

    @ez.publisher(OUTPUT_TARGET_CLASS)
    async def output_class(self) -> typing.AsyncGenerator:
        while True:
            out_class = await self.STATE.output_classes.get()
            yield self.OUTPUT_TARGET_CLASS, out_class

    # @ez.publisher(OUTPUT_TARGET_STIMTYPE)
    # async def output_stimtype(self) -> typing.AsyncGenerator:
    #     while True:
    #         out_st = await self.STATE.output_stimtype.get()
    #         yield self.OUTPUT_TARGET_STIMTYPE, out_st
    

    async def task_implementation(self) -> typing.AsyncIterator[SampleTriggerMessage | None]:
        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            classes: typing.List[str] = self.STATE.classes.value # type: ignore
            trials_per_class: int = self.STATE.trials_per_class.value # type: ignore
            trial_dur: float = self.STATE.trial_duration.value # type: ignore
            iti_min: float = self.STATE.intertrial_min_dur.value # type: ignore
            iti_max: float = self.STATE.intertrial_max_dur.value # type: ignore
            pre_run_duration: float = self.STATE.pre_run_duration.value # type: ignore
            post_run_duration: float = self.STATE.post_run_duration.value # type: ignore

            # save original ordering of classes for consistent drawing of stimuli
            classes_orig = classes 

            ''' create trial order (blockwise randomized) '''
            trials: typing.List[str] = []
            for _ in range(trials_per_class):
                random.shuffle(classes)
                trials += classes
            
            self.STATE.progress.max = len(trials)
            self.STATE.progress.value = 0
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            ''' run starts here '''
            self.STATE.status.value = 'Pre Run'
            await asyncio.sleep(pre_run_duration)

            # note: trials is array containing shuffled arrays of classes
            for trial_idx, trial_class in enumerate(trials):
                # start trial #
                trial_id = f'Trial {trial_idx + 1} / {len(trials)}'
                
                # ITI
                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                # draw all 3 fixations during ITI
                for i in np.arange(len(classes_orig)):
                    self.STATE.stim_indications[i].object = None
                    self.STATE.stimuli[i].object = self.STATE.fixations[i]
                self.STATE.output_classes.put_nowait(None)
                await asyncio.sleep(iti)

                # Stimulus Presentation
                self.STATE.status.value = f'{trial_id}: Action ({trial_class})'
                # loop through all classes, add fixation to trial class
                for i in np.arange(len(classes_orig)):
                    #TODO: add fixation on proper stim
                    stim = self.STATE.stimulus_map[classes_orig[i]] # index w/ key - string rep of class
                    stimulus_kwargs = dict(size = 500)
                    if(trial_class == classes_orig[i]):
                        self.STATE.stim_indications[i].object = self.STATE.indications[i]
                        self.STATE.stimuli[i].object = stim
                    else:
                        self.STATE.stimuli[i].object = stim
                self.STATE.output_classes.put_nowait(trial_class)
                yield SSVEPSampleTriggerMessage(
                    period = (0.0, trial_dur), 
                    value = trial_class,
                    expected_freq = 1.0 / stim.duration,
                    freqs = self.STATE.freqs
                )
                await asyncio.sleep(trial_dur)
                self.STATE.progress.value = trial_idx + 1
            
            self.STATE.status.value = 'Post Run'
            for i in np.arange(len(classes_orig)):
                self.STATE.stimuli[i].object = self.STATE.fixations[i]
                self.STATE.stim_indications[i].object = None
            self.STATE.output_classes.put_nowait(None)
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            for i in np.arange(len(classes_orig)):
                self.STATE.stim_indications[i].object = None
                self.STATE.stimuli[i].object = self.STATE.fixations[i]
            self.STATE.task_controls.disabled = False

    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls, 
                title = 'Multiple Steady State Visually Evoked Potentials'
            )
        ])
        return sidebar

class MultiSSVEPTask(Task):
    INPUT_CLASS = ez.InputStream(typing.Optional[typing.List[str]])
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[typing.List[str]])
    # INPUT_STIMTYPE = ez.InputStream(typing.Optional[str])
    # OUTPUT_TARGET_STIMTYPE = ez.OutputStream(typing.Optional[str])

    TASK: MultiSSVEPTaskImplementation = MultiSSVEPTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network()) + [
            (self.INPUT_CLASS, self.TASK.INPUT_CLASS),
            (self.TASK.OUTPUT_TARGET_CLASS, self.OUTPUT_TARGET_CLASS),
            # (self.INPUT_STIMTYPE, self.TASK.INPUT_STIMTYPE),
            # (self.TASK.OUTPUT_TARGET_STIMTYPE, self.OUTPUT_TARGET_STIMTYPE)
        ]
