import sublime
import sublime_plugin
import re
import operator
import time
import uuid
import subprocess
import tempfile
import os
import json
import sys
import hashlib
from os.path import expanduser, normpath, join, isfile


# ========================================
# history_manager.py
# ========================================
class HistoryHandler(object):
    _stack = None
    index = 0

    @classmethod
    def setup(cls, items):
        cls._stack = [''] + items
        cls.index = 0

    @classmethod
    def append(cls, value):
        # remove duplicate
        cls.remove(value)
        cls._stack.append(value)
        cls.index = 0

    @classmethod
    def remove(cls, value):
        if value in cls._stack:
            index = cls._stack.index(value)
            del cls._stack[index]

    @classmethod
    def set(cls, value, index=None):
        cls._stack[cls.normalize_index(index)] = value

    @classmethod
    def normalize_index(cls, index):
        original = index
        index = cls.index if index is None else index
        if index:
            last = len(cls._stack) - 1 if len(cls._stack) > 0 else 0
            # check if index is in bounds
            if index < 0:
                index = last
            if index > last:
                index = 0
        return index

    @classmethod
    def next(cls):
        cls.index = cls.normalize_index(cls.index + 1)

    @classmethod
    def prev(cls):
        cls.index = cls.normalize_index(cls.index - 1)

    @classmethod
    def get(cls, index=None):
        return cls._stack[cls.normalize_index(index)]

    @classmethod
    def empty(cls):
        return len(cls._stack) == 0

    @classmethod
    def size(cls):
        return len(cls._stack)

    @classmethod
    def current_index(cls):
        return cls.index


class HistoryManager(object):
    file = None

    def __init__(self, remove_duplicates=True):
        self.settings = sublime.load_settings(self.file)
        self.remove_duplicates = remove_duplicates

    def generate_key(self, data):
        return hashlib.md5(json.dumps(data).encode('UTF-8')).hexdigest()

    def history(self):
        history = self.settings.get("history", [])
        if isinstance(history, dict):
            history = []
        return history

    def items(self):
        entries = [item['data'] for item in self.history() if 'data' in item]
        return entries[-self.max():]

    def max(self):
        return self.settings.get("history_max_entries", 100)

    def save(self, history):
        if history is not None:
            self.settings.set("history", history)
        sublime.save_settings(self.file)

    def append(self, data, label=None):
        if not data:
            return
        history = self.history()
        key = self.generate_key(data)
        # convert
        if isinstance(history, dict):
            history = []
        history[:] = [item for item in history if 'key' in item and not item['key'] == key]
        history.append({'key': key, 'data': data, 'label': label})
        # set as last command
        self.settings.set('last_command', data)
        self.save(history)

    def remove(self, key):
        history = self.history()
        history[:] = [item for item in history if item['key'] == key]

    def clear(self):
        self.save([])


# ========================================
# history_navigator.py
# ========================================
class TextPastryHistoryNavigatorCommand(sublime_plugin.TextCommand):

    def __init__(self, *args, **kwargs):
        super(TextPastryHistoryNavigatorCommand, self).__init__(*args, **kwargs)
        self.current = None

    def run(self, edit, reverse=False):
        HH = HistoryHandler
        if HH.index == 0:
            current = self.view.substr(sublime.Region(0, self.view.size()))
            HH.set(current)
        if reverse:
            HH.prev()
        else:
            HH.next()
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, HH.get())
        if HH.current_index():
            sublime.status_message("History item: " + str(HH.current_index()) + " of " + str(HH.size() - 1))
        else:
            sublime.status_message("Current")

    def is_enabled(self, *args, **kwargs):
        return not HistoryHandler.empty()


# ========================================
# text_pastry_history_manager.py
# ========================================
class TextPastryHistoryManager(HistoryManager):
    file = "TextPastryHistory.sublime-settings"
    field = 'text'

    def generate_key(self, data):
        return hashlib.md5(data[self.field].encode('UTF-8')).hexdigest()

    def items(self):
        entries = [item['data'][self.field] for item in self.history() if 'data' in item and self.field in item['data']]
        return entries[-self.max():]

    def append(self, data, label=None):
        if self.field in data and len(data[self.field]) > 0:
            super(TextPastryHistoryManager, self).append(data, label)
            HistoryHandler.append(data[self.field])


class OverlayHistoryManager(HistoryManager):
    file = "TextPastryHistory.sublime-settings"
    field = 'text'

    def generate_key(self, data):
        return hashlib.md5(data[self.field].encode('UTF-8')).hexdigest()

    def items(self):
        entries = self.history()[-self.max():]
        entries.reverse()
        return entries

    def append(self, data, label=None):
        if self.field in data and len(data[self.field]) > 0:
            super(TextPastryHistoryManager, self).append(data, label)
            HistoryHandler.append(data[self.field])


# ========================================
# overlay.py
# ========================================
class Overlay(object):

    def __init__(self):
        self._items = []

    def addMenuItem(self, command, label, args=None):
        self._items.append(
            MenuItem(command=command, args=args, label=label)
        )

    def addSpacer(self):
        self._items.append(SpacerItem())

    def addHistoryItem(self, item):
        self._items.append(HistoryItem.from_item(item))

    def addSetting(self, name, value):
        self._items.append(SettingItem(
            'text_pastry_setting',
            {"name": name, "value": value}, name))

    def get(self, index):
        item = None
        if index >= 0 and index < len(self._items):
            item = self._items[index]
        return item

    def items(self):
        min_size = 0
        command_column_size = label_column_size = min_size
        # check width
        for idx, item in enumerate(self._items):
            (command_width, label_width) = item.width(idx)
            if command_width > command_column_size:
                command_column_size = command_width
            if label_width > label_column_size:
                label_column_size = label_width
        return [item.format(command_column_size, label_column_size, idx) for idx, item in enumerate(self._items)]

    def is_valid(self):
        return self._items and len(self._items) > 0

    def length(self):
        return len(self._items)


class OverlayItem(object):
    type = 0

    def __init__(self, command=None, args=None, label=None, text=None, separator=None):
        self.command = command
        self.args = args
        self.label = label
        self.text = text
        self.separator = separator

    def width(self, width):
        padding = 2
        command_width = len(self.command) + padding if self.command else 0
        label_width = len(self.label) + padding if self.label else 0
        return (command_width, label_width)


class MenuItem(OverlayItem):

    def format(self, command_width, label_width, index):
        text = self.command.ljust(command_width, ' ')
        text += self.label
        return text


class SettingItem(OverlayItem):

    def enabled(self):
        return self.args.get('value', False)

    def checkbox(self):
        return "[ X ]" if self.enabled() else "[   ]"

    def format(self, command_width, label_width, index):
        return self.checkbox() + "  " + self.label

    def width(self, index):
        return (len(self.checkbox()) + 2, 0)


class HistoryItem(OverlayItem):
    type = 2

    @classmethod
    def from_item(cls, item):
        data = item.get('data')
        if data and 'command' in data:
            return cls(command=data["command"], args=data["args"], label=item["label"], text=data["text"])
        return None

    def command_name(self, index):
        return '!hist_' + str(index + 1)

    def format(self, command_size, label_size, index):
        text = self.command_name(index).ljust(command_size, ' ')
        text += self.label
        return text

    def width(self, index):
        command = self.command_name(index)
        command_width = len(command) if command else 0
        label_width = len(self.label) if self.label else 0
        return (command_width, label_width)


class SpacerItem(OverlayItem):
    type = 3

    def format(self, command_width, label_width, index):
        return ""

    def width(self, index):
        return (0, 0)


# ========================================
# commands.py
# ========================================
class Command(object):

    def __init__(self, options=None, view=None, edit=None):
        self.counter = 0
        self.options = options
        self.stack = []
        self.view = view
        self.edit = edit

    def init(self, view, items=None):
        if items:
            self.stack = items

    def previous(self):
        return self.stack[self.counter - 1]

    def current(self):
        return text[self.counter]

    def next(self, value, index, region):
        val = self.stack[self.counter]
        self.counter += 1
        return val

    def has_next(self):
        return (self.counter) < len(self.stack)

    @staticmethod
    def create(cmd, items=None, options=None):
        return getattr(sys.modules[__name__], cmd)(items)


class UUIDCommand(Command):

    def next(self, value, index, region):
        text = str(uuid.uuid4())
        if self.is_upper_case():
            text = text.upper()
        self.stack.append(text)
        return text

    def is_upper_case(self):
        upper_case = False
        if self.options:
            upper_case = self.options.get("uppercase", False)
        return upper_case

    def has_next(self):
        return True


class BackreferenceCommand(Command):

    def init(self, view, items=None):
        selections = []
        if view.sel():
            for region in view.sel():
                selections.append(view.substr(region))
        values = []
        for idx, index in enumerate(map(int, items)):
            if idx >= len(selections):
                break
            i = index - 1
            if i >= 0 and i < len(selections):
                values.append(selections[i])
            else:
                values.append(None)
        # fill up
        for idx, value in enumerate(selections):
            if len(values) + 1 < idx:
                values.append(value)
        self.stack = values


class NodejsCommand(Command):

    def has_next(self):
        return True

    def next(self, value, index, region):
        file = self.options.get("file", None)
        folder = self.options.get("folder", None)
        script = self.options.get("script", None)
        sugar = self.options.get("sugar", True)
        if file:
            folder = folder if folder else expanduser("~")
            file = normpath(join(folder, file))
            if isfile(file):
                with open(file, "r") as f:
                    script = f.read()
        elif script and sugar:
            if not 'return ' in script and not ';' in script:
                script = "value = " + script
            script = 'var result=(function(value, index, begin, end){{{SCRIPT};return value;}}({VALUE}, {INDEX}, {BEGIN}, {END}));process.stdout.write('' + result);'.format(
                SCRIPT=script,
                VALUE=json.dumps(value),
                INDEX=index,
                BEGIN=region.a,
                END=region.b
            )
        if not script:
            print('No script found, canceling')
            return None
        cmd = "/usr/local/bin/node"
        cwd = expanduser("~")
        print('Running nodejs script:', script)
        proc = subprocess.Popen([cmd, '-e', script], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        result = proc.communicate()[0]
        if proc.returncode == 0:
            print('script result:', result.decode('UTF-8'))
            return result.decode('UTF-8')
        else:
            print('error while processing script:', result.decode('UTF-8'))
        return None


# ========================================
# parser.py
# ========================================
class Parser:

    def parse(self, text):
        if not text:
            return None
        # start pasing the command string
        result = None
        m5 = re.match('^(\$\d+\s?)+$', text)
        m8 = re.match('^cmd ([\w_]+)(.*?)', text)
        if m5:
            # backref
            items = ','.join(filter(None, map(lambda x: x.strip(), text.split('$'))))
            result = dict(command='text_pastry_insert', args={'command': 'backreference', 'text': items, 'separator': ','})
        elif m8:
            cmd = m8.group(1)
            args = m8.group(2)
            if args:
                args = ast.literal_eval('dict(' + args + ')')
            result = {'command': cmd, 'args': args}
        else:
            settings = sublime.load_settings('TextPastry.sublime-settings')
            cmd_shortcuts = settings.get('cmd_shortcuts')
            shortcuts = {}
            for item in cmd_shortcuts:
                shortcuts['match'] = item
            # look for cmd in shortcuts
            if text in shortcuts:
                result = self.create_command(shortcuts[text])
            if not result:
                # check regex
                for item in cmd_shortcuts:
                    comp = re.compile(item['match'])
                    match = comp.match(text)
                    if match:
                        # create dict with backreferences
                        refs = {}
                        for (key, value) in enumerate(match.groups()):
                            refs['$' + str(key + 1)] = value
                        # add other stuff to references
                        refs['$clipbord'] = sublime.get_clipboard()
                        result = self.create_command(item, refs)
                        break
            if not result:
                # default is words
                sublime.status_message('Inserting text: ' + text)
                result = dict(command='text_pastry_insert_text', args={'text': text, 'threshold': settings.get('insert_text_threshold', 3)})
        # Parser is done
        if result:
            #print('parsing done, result:', result)
            sublime.status_message('Running ' + result['command'])
        else:
            print('Text Pastry: no match found, doing nothing')
        return result

    def create_command(self, shortcut, refs=None):
        cmd = shortcut['command']
        args = None
        if 'args' in shortcut:
            args = shortcut['args']
        if refs and args:
            # text = re.sub(r'([^\\])\$(\d+)', r'(\2)', json.dumps(args)))
            # args = json.loads(text)
            return CommandParser(cmd, args, refs).create_command()
        return dict(command=cmd, args=args)


class CommandParser(object):

    def __init__(self, command, args, refs=None):
        self.command = command
        self.args = args
        self.refs = refs

    def parse(self, args):
        arr = {}
        for key, value in args.items():
            if isinstance(value, dict):
                arr[key] = self.parse(value)
            elif value:
                arr[key] = self.inject(value)
            else:
                arr[key] = value
        return arr

    def inject(self, value):
        if str(value) in self.refs:
            value = self.refs[str(value)]
        return value

    def create_command(self):
        if self.refs:
            args = self.parse(self.args)
            return dict(command=self.command, args=args)
        return dict(command=self.command, args=self.args)


# ========================================
# paste.py
# ========================================
class TextPastryPasteCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        try:
            text = sublime.get_clipboard()
            if text is not None and len(text) > 0:
                regions = []
                sel = self.view.sel()
                items = text.split("\n")
                if len(items) == 1:
                    items = [text]
                strip = True
                settings = sublime.load_settings("TextPastry.sublime-settings")
                for idx, region in enumerate(sel):
                    if idx < len(items):
                        row = items[idx].strip()
                        if region.empty():
                            sublime.status_message("empty")
                            row = self.view.substr(self.view.line(self.view.line(region).begin() - 1)) + "\n"
                            i = 0
                            if len(row.strip()):
                                i = self.view.insert(edit, region.end(), row)
                            regions.append(sublime.Region(region.end() + i, region.end() + i))
                        else:
                            sublime.status_message("selection")
                            self.view.replace(edit, region, row)
                            i = len(row)
                            regions.append(sublime.Region(region.begin() + i, region.begin() + i))
                sel.clear()
                for region in regions:
                    sel.add(region)
                    pass
            else:
                sublime.status_message("No text found for Insert Text, canceled")
        except ValueError:
            sublime.status_message("Error while executing Insert Text, canceled")
            pass


# ========================================
# redo.py
# ========================================
class TextPastryRedoCommand(sublime_plugin.WindowCommand):

    def run(self):
        hs = sublime.load_settings(TextPastryHistory.file_name)
        item = hs.get("last_command", {})
        if item and "command" in item and "text" in item and item["command"] and item["text"]:
            text = item.get("text")
            separator = item.get("separator", None)
            command = item.get("command", None)
            if text and command:
                sublime.status_message("Running last command")
                if command == "insert_nums":
                    (current, step, padding) = map(str, text.split(" "))
                    self.window.active_view().run_command(command, {"current": current, "step": step, "padding": padding})
                elif command == "text_pastry_insert_text":
                    self.window.active_view().run_command(command, {"text": text, "separator": separator})
                else:
                    pass


# ========================================
# insert_text.py
# ========================================
class TextPastryInsertTextCommand(sublime_plugin.TextCommand):

    def run(self, edit, text=None, separator=None, clipboard=False,
            items=None, regex=False, keep_selection=None, repeat=None, strip=None,
            threshold=1):
        try:
            if separator:
                separator = separator.encode('utf8').decode("unicode-escape")
            if clipboard:
                text = sublime.get_clipboard()
            if text:
                if regex:
                    items = re.split(separator, text)
                else:
                    items = text.split(separator)
            # could make a threshold setting...
            if items and len(items) >= threshold:
                regions = []
                sel = self.view.sel()
                if strip is None:
                    strip = False
                    settings = sublime.load_settings("TextPastry.sublime-settings")
                    if separator == "\n" and settings.has("clipboard_strip_newline"):
                        strip = settings.get("clipboard_strip_newline")
                if repeat is None:
                    if clipboard and settings.has("repeat_clipboard"):
                        repeat = settings.get("repeat_clipboard")
                    elif settings.has("repeat_words"):
                        repeat = settings.get("repeat_words")
                if repeat and items:
                    while (len(items) < len(sel)):
                        items.extend(items)
                last_region = None
                for idx, region in enumerate(sel):
                    if idx < len(items):
                        current = items[idx]
                        if (strip):
                            current = current.strip()
                        self.view.replace(edit, region, current)
                    else:
                        regions.append(region)
                    last_region = region
                if keep_selection is None:
                    keep_selection = settings.get("keep_selection", False)
                if not keep_selection:
                    sel.clear()
                    # add untouched regions
                    for region in regions:
                        sel.add(sublime.Region(region.begin(), region.end()))
                    # add cursor if there is none in the current view
                    if not sel:
                        sel.add(sublime.Region(last_region.end(), last_region.end()))
            else:
                sublime.status_message("No text found for Insert Text, canceled")
        except ValueError:
            sublime.status_message("Error while executing Insert Text, canceled")
            pass


# ========================================
# text_commands.py
# ========================================
class TextPastrySettingCommand(sublime_plugin.TextCommand):

    def run(self, edit, name, value):
        settings = sublime.load_settings("TextPastry.sublime-settings")
        settings.set(name, value)
        sublime.save_settings("TextPastry.sublime-settings")


class TextPastryUuidCommand(sublime_plugin.TextCommand):

    def run(self, edit, uppercase=False):
        settings = sublime.load_settings("TextPastry.sublime-settings")
        uppercase = settings.get("force_uppercase_uuid", False) or uppercase
        self.view.run_command("text_pastry_command_wrapper", {
            "command": "UUIDCommand",
            "args": {"uppercase": uppercase}
        })


class TextPastryNodejsCommand(sublime_plugin.TextCommand):

    def run(self, edit, file=None, folder=None, script=None, sugar=True):
        self.view.run_command("text_pastry_command_wrapper", {
            "command": "NodejsCommand",
            "args": {
                "file": file,
                "folder": folder,
                "script": script,
                "sugar": sugar
            }
        })


# ========================================
# command_line.py
# ========================================
class TextPastryShowCommandLine(sublime_plugin.WindowCommand):

    def run(self, text):
        if not self.window.active_view():
            return
        if not hasattr(self, 'history'):
            self.history = TextPastryHistoryManager()
            HistoryHandler.setup(self.history.items())
        self.show_input_panel('Text Pastry Command:', text)

    def on_done(self, text):
        parser = Parser()
        result = parser.parse(text)
        if result and 'command' in result:
            result['text'] = text
            self.history.append(data=result, label=text)
            command = result['command']
            args = result['args'] if 'args' in result else None
            self.window.active_view().run_command(command, args)

    def show_input_panel(self, label, text):
        HistoryHandler.index = 0
        view = self.window.show_input_panel(label, text, self.on_done, None, None)
        settings = view.settings()
        # this will be a setting in 1.4.0
        #settings.set('color_scheme', 'Packages/Color Scheme - Default/Mac Classic.tmTheme')
        settings.set('is_widget', False)
        settings.set('gutter', False)
        settings.set('rulers', [])
        settings.set('spell_check', False)
        settings.set('word_wrap', False)
        settings.set('draw_minimap_border', False)
        settings.set('draw_indent_guides', False)
        settings.set('highlight_line', False)
        settings.set('line_padding_top', 0)
        settings.set('line_padding_bottom', 0)
        settings.set('auto_complete', False)
        view.set_name('text_pastry_command_line')
        view.set_syntax_file('Packages/Text Pastry/TextPastry.xml')


# ========================================
# command_wrapper.py
# ========================================
class TextPastryCommandWrapperCommand(sublime_plugin.TextCommand):

    def run(self, edit, command, args=None, text=None, separator=None, items=None):
        try:
            cmd = Command.create(command, args)
            if cmd:
                items = items
                if text:
                    items = text.split(separator)
                cmd.init(self.view, items)
                regions = []
                sel = self.view.sel()
                index = 0
                last_region = None
                for region in sel:
                    if cmd.has_next():
                        value = cmd.next(self.view.substr(region), index, region)
                        if value is not None:
                            self.view.replace(edit, region, value)
                            regions.append(region)
                    else:
                        break
                    index += 1
                for region in regions:
                    # TODO: check keep_selection flag
                    sel.subtract(region)
            else:
                sublime.status_message("Command not found: " + cmd)
        except ValueError:
            sublime.status_message("Error while executing Text Pastry, canceled")
            pass


# ========================================
# show_menu.py
# ========================================
class TextPastryShowMenu(sublime_plugin.WindowCommand):

    def create_main(self):
        self.overlay = Overlay()
        settings = sublime.load_settings("TextPastry.sublime-settings")
        history = self.history_manager.items()
        [self.overlay.addHistoryItem(item) for item in history[:2]]
        if len(history) > 0:
            self.overlay.addSpacer()
        x = selection_count = len(self.window.active_view().sel())
        self.overlay.addMenuItem("\\i", "From 1 to {0}".format(x))
        self.overlay.addMenuItem("\\i0", "From 0 to " + str(x - 1))
        self.overlay.addMenuItem("\\i(N,M)", "From N to X by M")
        self.overlay.addSpacer()
        if sublime.get_clipboard():
            self.overlay.addMenuItem("\\p(\\n)", "Paste Lines")
            self.overlay.addMenuItem("\\p", "Paste")
            self.overlay.addSpacer()
        self.overlay.addMenuItem("words", "Enter a list of words")
        uuid_label = 'UUID' if settings.get("force_uppercase_uuid", False) else 'uuid'
        self.overlay.addMenuItem(uuid_label, "Generate UUIDs")
        self.overlay.addSpacer()
        if len(history) > 0:
            self.overlay.addMenuItem("history", "Show history")
        self.overlay.addMenuItem("settings", "Show settings")

    def create_history(self):
        self.overlay = Overlay()
        history = self.history_manager.items()
        [self.overlay.addHistoryItem(item) for item in history]
        self.overlay.addSpacer()
        self.overlay.addMenuItem("clear_hist", "Clear history")
        self.overlay.addMenuItem("back", "Back to menu")

    def create_settings(self):
        self.overlay = Overlay()
        settings = sublime.load_settings("TextPastry.sublime-settings")
        repeat_words = settings.get("repeat_words", False)
        repeat_clipboard = settings.get("repeat_clipboard", False)
        clipboard_strip_newline = settings.get("clipboard_strip_newline", False)
        keep_selection = settings.get("keep_selection", False)
        force_uppercase_uuid = settings.get("force_uppercase_uuid", False)
        self.overlay.addSetting("repeat_words", repeat_words)
        self.overlay.addSetting("repeat_clipboard", repeat_clipboard)
        self.overlay.addSetting("clipboard_strip_newline", clipboard_strip_newline)
        self.overlay.addSetting("keep_selection", keep_selection)
        self.overlay.addSetting("force_uppercase_uuid", force_uppercase_uuid)
        self.overlay.addSpacer()
        self.overlay.addMenuItem(command="default", args={"file": sublime.packages_path() + "/Text Pastry/TextPastry.sublime-settings"}, label="Open default settings")
        self.overlay.addMenuItem(command="user", args={"file": sublime.packages_path() + "/User/TextPastry.sublime-settings"}, label="Open user settings")
        if self.back:
            self.overlay.addSpacer()
            self.overlay.addMenuItem("back", "Back to menu")

    def run(self, history=False, settings=False, back=True):
        if not self.window.active_view():
            return
        if not hasattr(self, 'history_manager'):
            self.history_manager = OverlayHistoryManager()
        self.back = back
        try:
            selection_count = len(self.window.active_view().sel())
            if history:
                self.create_history()
            elif settings:
                self.create_settings()
            else:
                self.create_main()
            if self.overlay and self.overlay.is_valid():
                self.show_quick_panel(self.overlay.items(), self.on_done, sublime.MONOSPACE_FONT)
        except ValueError:
            sublime.status_message("Error while showing Text Pastry overlay")

    def on_done(self, index):
        self.window.run_command("hide_overlay")
        item = self.overlay.get(index)
        if item and item.command:
            if item.type == HistoryItem.type:
                sublime.status_message("redo history")
                command = item.command
                text = item.text
                separator = item.separator
                if command == "insert_nums":
                    sublime.status_message("insert_nums: " + text)
                    (current, step, padding) = map(str, text.split(" "))
                    self.window.run_command(command, {"current": current, "step": step, "padding": padding})
                elif command == "text_pastry_insert_text":
                    self.window.run_command(command, {"text": text, "separator": separator})
                else:
                    self.window.run_command(item.command, item.args)
            elif item.command == "history":
                self.window.run_command("text_pastry_show_menu", {"history": True})
                return
            elif item.command == "settings":
                self.window.run_command("text_pastry_show_menu", {"settings": True})
                return
            elif item.command == "clear_hist":
                self.history_manager.clear()
            elif item.command == "back":
                self.window.run_command("text_pastry_show_menu")
            elif item.command == "cancel" or item.command == "close":
                pass
            elif item.command == "\\p":
                cb = sublime.get_clipboard()
                if cb:
                    self.history_manager.append(data={"command": "text_pastry_insert_text", "args": {"clipboard": True}}, label=item.label)
                    self.window.run_command("text_pastry_insert_text", {"text": cb, "clipboard": True})
                else:
                    sublime.message_dialog("No Clipboard Data available")
            elif item.command == "\\p(\\n)":
                cb = sublime.get_clipboard()
                if cb:
                    self.history_manager.append(data={"command": "text_pastry_insert_text", "args": {"text": cb, "separator": "\\n", "clipboard": True}}, label=item.label)
                    self.window.run_command("text_pastry_insert_text", {"text": cb, "separator": "\\n", "clipboard": True})
                else:
                    sublime.message_dialog("No Clipboard Data available")
            elif item.command == "\\i":
                self.history_manager.append(data={"command": "insert_nums", "args": {"current": "1", "step": "1", "padding": "1"}}, label=item.label)
                self.window.run_command("insert_nums", {"current": "1", "step": "1", "padding": "1"})
            elif item.command == "\\i0":
                self.history_manager.append(data={"command": "insert_nums", "args": {"current": "0", "step": "1", "padding": "1"}}, label=item.label)
                self.window.run_command("insert_nums", {"current": "0", "step": "1", "padding": "1"})
            elif item.command.lower() == "uuid":
                self.history_manager.append(data={"command": "text_pastry_uuid", "args": {"uppercase": False}}, label=item.label)
                self.window.run_command("text_pastry_uuid", {"uppercase": False})
            elif item.command == "words":
                self.window.run_command("text_pastry_show_command_line", {"text": item.command + " "})
            elif item.command == "text_pastry_setting":
                item.args['value'] = not item.args.get('value', False)
                self.window.run_command("text_pastry_setting", item.args)
                self.window.run_command("text_pastry_show_menu", {"settings": True, "back": self.back})
            elif item.command == "user" or item.command == "default":
                self.window.run_command("open_file", item.args)
            elif item.command == "\\i(N,M)":
                self.window.run_command("text_pastry_show_command_line", {"text": item.command})
            elif len(item.command):
                self.window.run_command(item.command, item.args)
            else:
                sublime.status_message("Unknown command: " + item.command)
        else:
            sublime.status_message("No item selected")

    def show_quick_panel(self, items, on_done, flags):
        # Sublime 3 does not allow calling show_quick_panel from on_done, so we need to set a timeout here.
        sublime.set_timeout(lambda: self.window.show_quick_panel(items, on_done, flags), 10)
