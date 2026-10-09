#!/usr/bin/python3

import gi
gi.require_version('Gtk', '3.0')
import sys, os, threading, queue, gettext
from searchEngine import compile_matcher, search_files
from gi.repository import Gio, Gtk, GLib, GObject, Pango, GdkPixbuf

gettext.install("Canellia@json", str(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')) + '/locale')

def launch(path):
    fileObj = Gio.File.new_for_path(path)
    Gio.app_info_launch_default_for_uri(fileObj.get_uri(), Gio.AppLaunchContext())


class SearchBox(Gtk.Entry):
    def __init__(self, searchCommand):
        Gtk.Entry.__init__(self)
        self.searchCommand = searchCommand

        self.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "edit-find-symbolic")
        self.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic")

        self.connect("icon-press", self.onClick)

        self.connect("activate", self.searchCommand)

    def onClick(self, target, pos, event):
        if pos == Gtk.EntryIconPosition.PRIMARY and self.get_text() != "":
            self.searchCommand()
        if pos == Gtk.EntryIconPosition.SECONDARY:
            self.set_text("")


class Context(Gtk.Menu):
    def __init__(self, parent):
        Gtk.Menu.__init__(self)

        self.parent = parent

        self.attach_to_widget(parent, None)

        launch = Gtk.MenuItem()
        launch.set_label(_("Open"))
        launch.connect("activate", self.launchItem)
        self.append(launch)

        openFolder = Gtk.MenuItem()
        openFolder.set_label(_("Open containing folder"))
        openFolder.connect("activate", self.openFolder)
        self.append(openFolder)

        parent.connect("button-press-event", self.onButtonPress)
        parent.connect("popup-menu", self.openContext)

        self.show_all()

    def onButtonPress(self, target, event):
        if event.button == 3:
            selection = target.get_selection()
            info = target.get_path_at_pos(int(event.x), int(event.y))
            if info is None:
                return True
            selection.select_path(info[0])
            self.openContext()
            return True

        return False

    def openContext(self, *args):
        self.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def launchItem(self, a):
        model, iter = self.parent.get_selection().get_selected()
        if iter is not None:
            launch(os.path.join(model[iter][2], model[iter][1]))

    def openFolder(self, a):
        model, iter = self.parent.get_selection().get_selected()
        if iter is not None:
            launch(model[iter][2])


class SearchWindow(Gtk.Window):
    searching = False

    def __init__(self, basePath):
        Gtk.Window.__init__(self, title=(_("Search")), icon_name="edit-find", default_height=400, default_width=650)
        self.connect("destroy", self.quit)

        self.search = None
        self._cancel = None
        self._generation = 0
        self._closed = False
        self._poll = 0
        self.results = Gtk.ListStore(str, str, str)

        mainBox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, border_width = 10)
        self.add(mainBox)

        contentBox = Gtk.Box(border_width=0)
        mainBox.pack_start(contentBox, True, True, 0)

        ## left pane
        leftPane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, border_width = 10)
        contentBox.pack_start(leftPane, False, False, 0)

        # search box
        self.searchBox = SearchBox(self.startSearch)
        leftPane.pack_start(self.searchBox, False, False, 5)

        # location selector
        leftPane.pack_start(Gtk.Label(_("Start in"), halign=Gtk.Align.START), False, False, 5)
        self.location = Gtk.FileChooserButton.new(_("Select a folder"), Gtk.FileChooserAction.SELECT_FOLDER)
        leftPane.add(self.location)
        if not basePath is None:
            self.location.set_filename(basePath)

        # follow symlinks
        self.symlinks = Gtk.CheckButton.new_with_label(_("Follow symlinks"))
        leftPane.add(self.symlinks)

        # display hidden files/folders
        self.hidden = Gtk.CheckButton.new_with_label(_("Search hidden"))
        leftPane.add(self.hidden)

        # use regex
        self.regex = Gtk.CheckButton.new_with_label(_("Use regular expressions"))
        leftPane.add(self.regex)

        # stop button
        self.stopButton = Gtk.Button(label = (_("Stop")), sensitive=False)
        leftPane.pack_end(self.stopButton, False, False, 5)
        self.stopButton.connect("clicked", self.stopSearch)

        ## right pane
        rightPane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, border_width = 10)
        contentBox.pack_start(rightPane, True, True, 0)

        # results display tree
        scrollBox = Gtk.ScrolledWindow()
        rightPane.pack_start(scrollBox, True, True, 5)
        tree = Gtk.TreeView(self.results)
        scrollBox.add(tree)

        fileNameColumn = Gtk.TreeViewColumn()
        fileNameColumn.set_title(_("File"))
        fileNameColumn.set_resizable(True)
        fileNameColumn.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        fileNameColumn.set_fixed_width(200)
        fileNameColumn.set_min_width(200)
        tree.append_column(fileNameColumn)

        iconRenderer = Gtk.CellRendererPixbuf()
        fileNameColumn.pack_start(iconRenderer, expand=False)
        fileNameColumn.add_attribute(iconRenderer, "icon-name", 0)

        fileNameRenderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        fileNameColumn.pack_start(fileNameRenderer, expand=False)
        fileNameColumn.add_attribute(fileNameRenderer, "text", 1)

        pathRenderer = Gtk.CellRendererText()
        pathColumn = Gtk.TreeViewColumn(_("Path"), pathRenderer, text=2)
        pathColumn.set_resizable(True)
        tree.append_column(pathColumn)

        # context menu
        Context(tree)
        tree.connect("row-activated", self.launchItem)

        # status text
        hbox = Gtk.Box()
        mainBox.pack_start(hbox, False, False, 0)
        self.currentLabel = Gtk.Label()
        self.currentLabel.set_ellipsize(Pango.EllipsizeMode.END)
        hbox.pack_start(self.currentLabel, False, False, 5)

        self.show_all()

    def quit(self, widget):
        self.stopSearch()
        self._closed = True
        Gtk.main_quit()

    def startSearch(self, a=None):
        self.stopSearch()
        directory = self.location.get_filename()
        try:
            if not directory or not os.path.isdir(directory):
                raise ValueError(_("Select a folder"))
            matcher = compile_matcher(self.searchBox.get_text(), self.regex.get_active())
        except Exception as error:
            self.setStatusText(str(error))
            return
        # Snapshot all GTK settings before the worker starts.
        hidden = self.hidden.get_active()
        follow = self.symlinks.get_active()
        self.results.clear()
        self.searching = True
        self._cancel = threading.Event()
        cancel = self._cancel
        generation = self._generation
        messages = queue.Queue(maxsize=256)
        self.stopButton.set_sensitive(True)
        self.setStatusText(_("Searching..."))

        def send(message):
            while not cancel.is_set():
                try:
                    messages.put(message, timeout=0.05)
                    return
                except queue.Full:
                    pass

        def worker():
            try:
                for result in search_files(directory, matcher, hidden, follow, cancel,
                                           lambda error: send(('error', error))):
                    name, folder, is_directory = result
                    fallback = 'folder' if is_directory else 'text-x-generic'
                    icons = [fallback]
                    try:
                        info = Gio.File.new_for_path(os.path.join(folder, name)).query_info('standard::icon', 0, None)
                        gicon = info.get_icon()
                        if hasattr(gicon, 'get_names'):
                            icons = list(gicon.get_names()) + icons
                    except GLib.Error:
                        pass  # Files can disappear or become inaccessible during a search.
                    send(('result', (name, folder, icons)))
            except Exception as error:
                send(('error', str(error)))
            finally:
                send(('done', None))

        errors = []
        def drain():
            if self._closed or generation != self._generation:
                return GLib.SOURCE_REMOVE
            for _index in range(128):
                try:
                    kind, data = messages.get_nowait()
                except queue.Empty:
                    break
                if kind == 'result':
                    name, folder, icons = data
                    self.addResult(name, folder, icons)
                elif kind == 'error':
                    errors.append(data)
                elif kind == 'done':
                    self.searching = False
                    self._poll = 0
                    self.stopButton.set_sensitive(False)
                    self.setStatusText(errors[-1] if errors else _("Search Completed"))
                    return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        self._poll = GLib.timeout_add(50, drain)
        self.search = threading.Thread(target=worker, daemon=True)
        self.search.start()

    def stopSearch(self, a=None):
        self._generation += 1
        self.searching = False
        if self._cancel is not None:
            self._cancel.set()
        if self._poll:
            GLib.source_remove(self._poll)
            self._poll = 0
        # Never join a filesystem worker from GTK's main thread.
        self.search = None
        self.stopButton.set_sensitive(False)
        if not self._closed:
            self.setStatusText(_("Search Stopped"))

    def launchItem(self, event, path, column):
        row = self.results[path]
        launch(os.path.join(row[2], row[1]))

    def addResult(self, fileName, path, icons):
        # GTK theme lookup runs on the UI thread; filesystem I/O stays in the worker.
        icon = next((name for name in icons if Gtk.IconTheme.get_default().has_icon(name)), icons[-1])
        self.results.append([icon, fileName, path])

    def setStatusText(self, text):
        self.currentLabel.set_text(text)


if __name__ == "__main__":
    SearchWindow(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~'))
    Gtk.main()
