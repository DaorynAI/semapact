import argparse
import sys
import io
from typing import List, Dict, Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widget import Widget
from textual.widgets import Header, Footer, OptionList, Static, Log, Input, Button, Label, Select
from textual.widgets.option_list import Option
from textual.binding import Binding
from textual import work

from textual.screen import ModalScreen
from textual.containers import Grid
from semapact.interfaces.cli import _build_parser, main as cli_main

class InitConfigModal(ModalScreen[bool]):
    CSS = """
    InitConfigModal {
        align: center middle;
    }
    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 0 1;
        width: 60;
        height: 11;
        border: thick $background 80%;
        background: $surface;
    }
    #question {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }
    Button {
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Grid(
            Label("No configuration file found.\\nWould you like to generate a default .semapact.yaml?", id="question"),
            Button("Yes, generate it", variant="primary", id="yes"),
            Button("No, maybe later", variant="error", id="no"),
            id="dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

class DynamicForm(Container):
    """A dynamically generated form based on argparse arguments."""

    def __init__(self, parser: argparse.ArgumentParser, command_name: str, command_help: str = ""):
        super().__init__()
        self.parser = parser
        self.command_name = command_name
        self.command_help = command_help
        self.fields: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Label(f"Command: {self.command_name}", classes="form-title")
        if self.command_help:
            yield Label(self.command_help, classes="form-description")
        yield Static("Fill in the arguments below:", classes="form-subtitle")

    def _create_widget_for_action(self, action: argparse.Action) -> Widget:
        field_id = f"field_{action.dest}"
        if action.choices:
            options = [(str(c), str(c)) for c in action.choices]
            default_val = str(action.default) if action.default is not None and str(action.default) in action.choices else Select.NULL
            select = Select(options, id=field_id, prompt="Select an option", value=default_val)
            self.fields[action.dest] = select
            return select
        elif action.nargs == 0 or isinstance(action, argparse._StoreTrueAction):
            select = Select([("True", "True"), ("False", "False")], id=field_id, prompt="False")
            self.fields[action.dest] = select
            return select
        else:
            default_val = str(action.default) if action.default is not None and action.default != argparse.SUPPRESS else ""
            input_widget = Input(placeholder=action.help or "", id=field_id, value=default_val)
            self.fields[action.dest] = input_widget
            return input_widget

    def compose(self) -> ComposeResult:
        from textual.widgets import Collapsible

        yield Label(f"Command: {self.command_name}", classes="form-title")
        if self.command_help:
            yield Label(self.command_help, classes="form-description")
        yield Static("Fill in the arguments below:", classes="form-subtitle")

        for group in self.parser._action_groups:
            actions = [a for a in group._group_actions if a.dest not in ("help", "command") and not isinstance(a, argparse._SubParsersAction)]
            if not actions:
                continue

            is_main_group = group.title in ("positional arguments", "options", "optional arguments")

            if is_main_group:
                for action in actions:
                    label_text = f"{action.dest}"
                    if action.required:
                        label_text += " (*)"
                    yield Label(label_text)
                    yield self._create_widget_for_action(action)
            else:
                widgets = []
                for action in actions:
                    label_text = f"{action.dest}"
                    if action.required:
                        label_text += " (*)"
                    widgets.append(Label(label_text))
                    widgets.append(self._create_widget_for_action(action))
                
                yield Collapsible(*widgets, title=group.title, collapsed=True)

        yield Button("Execute", id="execute-btn", variant="primary")

    def build_args_list(self) -> List[str]:
        args_list = self.command_name.split()
        for dest, widget in self.fields.items():
            action = next((a for a in self.parser._actions if a.dest == dest), None)
            if not action:
                continue

            value = None
            if isinstance(widget, Input):
                value = widget.value
            elif isinstance(widget, Select):
                value = widget.value

            if value and value != Select.NULL:
                if isinstance(action, argparse._StoreTrueAction):
                    if value == "True":
                        args_list.append(action.option_strings[0])
                else:
                    if action.option_strings:
                        args_list.append(action.option_strings[0])
                    args_list.append(str(value))
        return args_list


class SemaPactTUI(App):
    """A Textual App to navigate and execute semapact commands."""
    
    TITLE = "🏛️ SemaPact TUI"

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-container {
        height: 1fr;
        layout: horizontal;
    }
    #sidebar {
        width: 30;
        dock: left;
        border-right: solid green;
    }
    #banner {
        color: $accent;
        text-align: center;
        text-style: bold;
        padding: 1;
        border-bottom: dashed $accent;
    }
    #command-list {
        height: 1fr;
    }
    #content-area {
        width: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #log-panel {
        height: 10;
        border-top: solid green;
        dock: bottom;
        background: $surface-darken-1;
    }
    .form-title {
        text-style: bold;
        padding-bottom: 1;
        color: $accent;
    }
    .form-description {
        text-style: italic;
        padding-bottom: 1;
        color: $text-muted;
    }
    .form-subtitle {
        padding-bottom: 1;
    }
    Button {
        margin-top: 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, cli_parser: argparse.ArgumentParser = None, excluded_commands: List[str] = None):
        super().__init__()
        if cli_parser is None:
            self.cli_parser = _build_parser()
        else:
            self.cli_parser = cli_parser
            
        self.subparsers = self._extract_subparsers()
        
        exclude = excluded_commands if excluded_commands is not None else ["enrich", "tui"]
        
        self.commands = []
        for cmd in self.subparsers.keys():
            if not any(cmd == x or cmd.startswith(x + " ") for x in exclude):
                self.commands.append(cmd)

    def _extract_subparsers(self) -> Dict[str, tuple[argparse.ArgumentParser, str]]:
        flat_parsers = {}
        
        def traverse(parser, prefix="", help_str=""):
            has_subparsers = False
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    has_subparsers = True
                    for name, subparser in action.choices.items():
                        new_prefix = f"{prefix} {name}" if prefix else name
                        
                        sub_help = ""
                        for choice_action in action._choices_actions:
                            if choice_action.dest == name:
                                sub_help = choice_action.help or ""
                                break
                                
                        traverse(subparser, new_prefix, sub_help)
                        
            if not has_subparsers and prefix:
                flat_parsers[prefix] = (parser, help_str)

        traverse(self.cli_parser)
        return flat_parsers

    def compose(self) -> ComposeResult:
        from rich.text import Text
        yield Header()
        with Horizontal(id="main-container"):
            # Sidebar for commands
            with Vertical(id="sidebar"):
                banner_text = (
                    "  ___ _   _     \n"
                    " / __| |_| |__  \n"
                    "| (__|  _| '_ \\ \n"
                    " \\___|\\__|_.__/ \n"
                    " SemaPact  "
                )
                yield Static(banner_text, id="banner")
                
                # Group commands for visual clarity
                groups = {"GLOBAL": []}
                for cmd in self.commands:
                    parts = cmd.split()
                    if len(parts) == 1:
                        groups["GLOBAL"].append(cmd)
                    else:
                        group_name = parts[0].upper()
                        if group_name not in groups:
                            groups[group_name] = []
                        groups[group_name].append(cmd)
                
                options = []
                for group_name, cmds in groups.items():
                    if not cmds: 
                        continue
                    if options:
                        options.append(Option(Text(""), disabled=True, id=None))
                    
                    options.append(Option(Text(f" [ {group_name} ] ", style="bold green reverse"), disabled=True, id=None))
                    
                    for cmd in cmds:
                        _, help_str = self.subparsers[cmd]
                        display_cmd = cmd.split()[-1] if len(cmd.split()) > 1 else cmd
                        label = Text.assemble(("  " + display_cmd, "bold"), (" - ", "dim"), (help_str, "italic dim")) if help_str else f"  {display_cmd}"
                        options.append(Option(label, id=cmd))
                        
                yield OptionList(*options, id="command-list")

            # Main content area
            yield Vertical(id="content-area")

        yield Log(id="log-panel", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        from semapact.core.config import config_manager
        
        def handle_init(result: bool) -> None:
            if result:
                import argparse
                from semapact.interfaces.cli import _run_init
                _run_init(argparse.Namespace())
                config_manager._load_configs()
                
            if self.commands:
                self.load_command_form(self.commands[0])

        if not config_manager.config_data:
            self.push_screen(InitConfigModal(), handle_init)
        else:
            if self.commands:
                self.load_command_form(self.commands[0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        command_name = event.option.id
        self.load_command_form(command_name)

    def load_command_form(self, command_name: str) -> None:
        content_area = self.query_one("#content-area")
        content_area.remove_children()

        parser_info = self.subparsers.get(command_name)
        if parser_info:
            parser, cmd_help = parser_info
            content_area.mount(DynamicForm(parser, command_name, cmd_help))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "execute-btn":
            form = event.button.parent
            if isinstance(form, DynamicForm):
                args_list = form.build_args_list()
                self.execute_command(args_list)

    @work(thread=True)
    def execute_command(self, args_list: List[str]) -> None:
        log_panel = self.query_one("#log-panel", Log)
        self.call_from_thread(log_panel.write_line, f"> semapact {' '.join(args_list)}")

        # Capture stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        original_argv = sys.argv.copy()
        sys.argv = ["semapact"] + args_list

        try:
            # We run cli_main which returns an exit code
            exit_code = cli_main()
            stdout_str = sys.stdout.getvalue()
            stderr_str = sys.stderr.getvalue()

            if stdout_str:
                self.call_from_thread(log_panel.write_line, stdout_str)
            if stderr_str:
                self.call_from_thread(log_panel.write_line, f"ERR: {stderr_str}")
            self.call_from_thread(log_panel.write_line, f"Exited with code: {exit_code}\n")
        except Exception as e:
            self.call_from_thread(log_panel.write_line, f"Exception: {e}\n")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = original_argv

if __name__ == "__main__":
    app = SemaPactTUI()
    app.run()
