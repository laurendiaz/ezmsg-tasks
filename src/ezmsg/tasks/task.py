
import json
import asyncio
import typing
import datetime

from pathlib import Path

import ezmsg.core as ez
import panel as pn

from ezmsg.panel.tabbedapp import Tab
from ezmsg.sigproc.sampler import Sampler, SamplerSettings, SampleMessage, SampleTriggerMessage
from ezmsg.util.messagecodec import MessageEncoder, LogStart
from ezmsg.util.messages.axisarray import AxisArray

from param.parameterized import Event


class TaskException(Exception):
    ...

class TaskEndedEarly(TaskException):
    ...

class TaskComplete(TaskException):
    ...


class TaskSettings(ez.Settings):
    data_dir: Path
    buffer_dur: float = 10.0


class TaskImplementationState(ez.State):
    progress: pn.indicators.Progress
    status: pn.widgets.StaticText
    run_info: pn.widgets.StaticText
    run_button: pn.widgets.Button
    run_event: asyncio.Event
    status_card: pn.layout.Card

    recording_controls: pn.layout.WidgetBox
    recording_subdir: pn.widgets.TextInput
    recording_fname: pn.widgets.StaticText
    n_trials: pn.indicators.Number
    recording_card: pn.layout.Card

    recording_file: typing.Optional[typing.TextIO] = None

    trigger_queue: asyncio.Queue[SampleTriggerMessage]


class TaskImplementation(ez.Unit, Tab):

    # NOTE: For compatibility with TaskDirectory, 
    # Task implementations should NOT have derived settings
    # This should be a reasonable ask because we will have UI for such things

    SETTINGS: TaskSettings
    STATE: TaskImplementationState

    INPUT_SAMPLE = ez.InputStream(SampleMessage)
    OUTPUT_TRIGGER = ez.OutputStream(SampleTriggerMessage)
    
    @property
    def slug(self) -> str:
        """ Shortname used to identify recorded files """
        return 'TASK'

    @property
    def title(self) -> str:
        """ Full name of Task that appears in UI """
        return 'Task Implementation'
    
    async def initialize(self) -> None:
        
        sw = dict(sizing_mode = 'stretch_width')

        self.STATE.progress = pn.indicators.Progress(value = 1, max = 1, bar_color = 'success', **sw)
        self.STATE.status = pn.widgets.StaticText(name = 'Status', value = '', **sw)
        self.STATE.run_info = pn.widgets.StaticText(name = 'Run Info', **sw)
        self.STATE.run_button = pn.widgets.Button(name = 'Start Run', button_type = 'primary', **sw)
        self.STATE.run_event = asyncio.Event()

        async def on_run(_: Event) -> None:
            if self.STATE.run_event.is_set():
                self.STATE.run_button.name = 'Stopping...'
                self.STATE.run_button.disabled = True
                self.STATE.run_event.clear()
            else:
                self.STATE.run_button.name = 'Starting...'
                self.STATE.run_button.disabled = True
                self.STATE.run_event.set()
        
        self.STATE.run_button.on_click(on_run)

        self.STATE.status_card = pn.Card(
            self.STATE.status,
            self.STATE.progress,
            self.STATE.run_info,
            self.STATE.run_button,
            title = 'Status and Control',
        )

        self.STATE.recording_subdir = pn.widgets.TextInput(
            name = 'Recording Directory', 
            placeholder = 'Subdirectory name...',
            **sw
        )

        self.STATE.recording_fname = pn.widgets.StaticText(name = 'File', value = '', **sw)
        self.STATE.n_trials = pn.widgets.Number(value = 0, format = 'Recorded {value} Trials', font_size = '10pt', **sw)

        self.STATE.recording_controls = pn.layout.WidgetBox(
            self.STATE.recording_subdir,
            self.STATE.recording_fname,
            self.STATE.n_trials,
            **sw
        )

        self.STATE.recording_card = pn.layout.Card(
            self.STATE.recording_controls,
            title = 'Recording',
            **sw
        )
    
        self.STATE.trigger_queue = asyncio.Queue()

    @ez.publisher(OUTPUT_TRIGGER)
    async def pub_triggers(self) -> typing.AsyncGenerator:
        while True:
            trig = await self.STATE.trigger_queue.get()
            yield self.OUTPUT_TRIGGER, trig
    
    @ez.task    
    async def run_task(self) -> typing.AsyncGenerator:
            
        while True:
            self.STATE.progress.disabled = True
            self.STATE.status.value = 'Idle'
            await self.STATE.run_event.wait()

            self.STATE.run_button.name = 'Stop Run'
            self.STATE.run_button.disabled = False
            self.STATE.recording_subdir.disabled = True

            recording_subdir: typing.Optional[str] = self.STATE.recording_subdir.value # type: ignore

            style = {'color': 'green'}
            self.STATE.n_trials.value = 0
            if recording_subdir:
                timestr = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
                fname = f'{"-".join([timestr, self.slug])}.txt'
                record_file = self.SETTINGS.data_dir / 'recordings' / recording_subdir / fname
                self.STATE.recording_fname.value = '/'.join(record_file.parts[-2:])
                if not record_file.parent.exists():
                    record_file.parent.mkdir(parents = True, exist_ok = True)
                self.STATE.recording_file = open(record_file, 'w')
                start_msg = json.dumps(LogStart(), cls = MessageEncoder)
                self.STATE.recording_file.write(f'{start_msg}\n')
            else:
                style = {'color': 'red'}
                self.STATE.recording_fname.value = 'NOT RECORDING'
            self.STATE.recording_fname.styles = style

            try:
                async for trigger in self.task_implementation():
                    if trigger:
                        self.STATE.trigger_queue.put_nowait(trigger)
                    if not self.STATE.run_event.is_set():
                        raise TaskEndedEarly()

            except TaskEndedEarly:
                ez.logger.warning(f'{self.name} - Task ended early')
                self.STATE.progress.bar_color = 'warning'

            except TaskComplete:
                ez.logger.info(f'{self.name} - Task complete')
                self.STATE.progress.bar_color = 'success'

            finally:
                self.STATE.run_event.clear()
                self.STATE.run_button.name = 'Start Run'
                self.STATE.run_button.disabled = False

                self.STATE.recording_fname.styles = {}
                self.STATE.recording_subdir.disabled = False

                if self.STATE.recording_file is not None:
                    self.STATE.recording_file.flush()
                    self.STATE.recording_file.close()
                self.STATE.recording_file = None

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:
        yield None

    @ez.subscriber(INPUT_SAMPLE)
    async def on_sample(self, msg: SampleMessage) -> None:
        if self.STATE.recording_file:
            # FIXME: This should probably be done in a separate thread
            msg_ser = json.dumps(msg, cls = MessageEncoder)
            self.STATE.recording_file.write(f'{msg_ser}\n')
            self.STATE.n_trials.value += 1 # type: ignore
            

    def content(self):
        return pn.layout.Card(
            '# Task Area', 
            sizing_mode = 'stretch_both'
        )

    def sidebar(self):
        return pn.Column(
            self.STATE.status_card,
            self.STATE.recording_card
        )
    
class Task(ez.Collection, Tab):

    SETTINGS: TaskSettings

    TASK: TaskImplementation
    SAMPLER = Sampler()

    INPUT_TRIGGER = ez.InputStream(SampleTriggerMessage)
    INPUT_SIGNAL = ez.InputStream(AxisArray)
    OUTPUT_SAMPLE = ez.OutputStream(SampleMessage)

    def configure(self) -> None:
        self.TASK.apply_settings(self.SETTINGS)
        self.SAMPLER.apply_settings(
            SamplerSettings(
                buffer_dur = self.SETTINGS.buffer_dur + 1.0
            )
        )

    @property
    def title(self) -> str:
        return self.TASK.title
            
    def sidebar(self) -> pn.viewable.Viewable:
        return self.TASK.sidebar()
                
    def content(self) -> pn.viewable.Viewable:
        return self.TASK.content()
        
    def network(self) -> ez.NetworkDefinition:
        return (
            (self.INPUT_SIGNAL, self.SAMPLER.INPUT_SIGNAL),
            (self.INPUT_TRIGGER, self.SAMPLER.INPUT_TRIGGER),
            (self.TASK.OUTPUT_TRIGGER, self.SAMPLER.INPUT_TRIGGER),
            (self.SAMPLER.OUTPUT_SAMPLE, self.TASK.INPUT_SAMPLE),
            (self.SAMPLER.OUTPUT_SAMPLE, self.OUTPUT_SAMPLE)
        )