"""
PyChanEditor Copyright (C) 2014 Karsten Bock

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""

import gettext
import yaml
import os
from xml.sax._exceptions import SAXParseException

from fife import fife
from fife.extensions import pychan
from fife.extensions.pychan import GuiXMLError
from fife.extensions.pychan.pychanbasicapplication import PychanApplicationBase
from fife.extensions.pychan.widgets import VBox, HBox, ScrollArea
from fife.extensions.pychan.dialog.filebrowser import FileBrowser
from fife.extensions.pychan import attrs
from fife.extensions.pychan.tools import callbackWithArguments as cbwa
from fife.extensions.pychan.exceptions import ParserError

from editor.gui.menubar import MenuBar, Menu
from editor.gui.action import Action, ActionGroup, activated, toggled
from editor.gui.error import ErrorDialog
from editor.gui.editcontainer import EditContainer


class EditorEventListener(fife.IKeyListener, fife.ICommandListener):

    """Listener for the PyChanEditor"""
    def __init__(self, app):
        if False:
            self.app = EditorApplication()
        self.app = app
        self.engine = app.engine
        eventmanager = self.engine.getEventManager()
        fife.IKeyListener.__init__(self)
        eventmanager.addKeyListener(self)
        fife.ICommandListener.__init__(self)
        eventmanager.addCommandListener(self)

    def keyPressed(self, evt):  # pylint: disable-msg=W0221, C0103
        assert isinstance(evt, fife.KeyEvent)
        keyval = evt.getKey().getValue()
        if keyval == fife.Key.ESCAPE:
            self.app.quit()
        elif keyval == fife.Key.UP and evt.isControlPressed():
            selected = self.app.selected_widget
            if not selected:
                return
            parent = selected.parent
            if parent is not self.app.edit_window:
                self.app.select_widget(parent)
        elif keyval == fife.Key.DELETE:
            selected = self.app.selected_widget
            if not selected:
                return
            self.app.delete_widget(selected)

    def keyReleased(self, evt):  # pylint: disable-msg=W0221, C0103
        pass

    def onCommand(self, command):  # pylint: disable-msg=W0221, C0103
        if command.getCommandType() == fife.CMD_QUIT_GAME:
            self.app.quit()
            command.consume()


class WidgetItem(object):
    """Class to control how a widget appears in a list"""

    def __init__(self, widget):
        self._widget = widget

    @property
    def widget(self):
        """The contained widget"""
        return self._widget

    def __str__(self):
        return self.widget.name

    def __eq__(self, other):
        """Returns True if the the other widget is the same as the stored
        widget.
        """
        return other == self.widget


class EditorApplication(PychanApplicationBase):
    """The main class for the PyChanEditor"""

    DATA_PATH = "data/"
    FILEBROWSER_XML = DATA_PATH + "gui/filebrowser.xml"
    MENU_HEIGHT = 30
    TOOLBAR_HEIGHT = 60

    def __init__(self, setting=None):
        #for IDES:
        if False:
            self.engine = fife.Engine()
        self._listener = None
        PychanApplicationBase.__init__(self, setting)

        self.error_dialog = lambda msg: ErrorDialog(msg, self.DATA_PATH)

        vfs = self.engine.getVFS()
        vfs.addNewSource(self.DATA_PATH)

        self.__languages = {}
        self.__current_language = ""
        default_language = setting.get("i18n", "DefaultLanguage", "en")
        languages_dir = setting.get("i18n", "Directory", "__languages")
        for language in setting.get("i18n", "Languages", ("en",)):
            fallback = (language == default_language)
            self.__languages[language] = gettext.translation("PyChanEditor",
                                                            languages_dir,
                                                            [language],
                                                            fallback=fallback)
        language = setting.get("i18n", "Language", default_language)
        self.switch_language(language)

        self._engine_settings = self.engine.getSettings()
        self._markers = {}
        self._main_window = None
        self._toolbar_area = None
        self._toolbar = None
        self._menubar = None
        self._file_menu = None
        self._window_menu = None
        self._bottom_window = None
        self._edit_tab = None
        self._edit_window = None
        self._edit_wrapper = None
        self._right_window = None
        self._widget_combo = None
        self._property_area = None
        self._property_window = None
        self._selected_widget = None
        self._project_data_path = None
        self._marker_dragged = False
        self._widget_dragged = False
        self._old_x = 0
        self._old_y = 0
        self._widgets = []
        self._guis = {}
        self._gui_actions = ActionGroup(exclusive=True, name="GuiActions")
        toggled.connect(self.cb_select_gui, self._gui_actions)
        self._current_gui = None
        self._current_gui_path = None

        self.init_gui(self._engine_settings.getScreenWidth(),
                      self._engine_settings.getScreenHeight())
        gui_action = self.new_gui("main")
        gui_action.setChecked(True)
        self.select_widget(self._guis["main"])

    @property
    def selected_widget(self):
        """The widget that is currently selected"""
        return self._selected_widget

    @property
    def edit_window(self):
        """The window that contains the gui to be edited"""
        return self._edit_window

    def key_pressed(self, event):
        """Receives key events from widgets and passes them to the listener

        Args:

            event: The fifechan event
        """
        if self._listener is not None:
            self._listener.keyPressed(event)

    def init_gui(self, screen_width, screen_height):
        """Initialize the gui

        Args:

            screen_width: The width the elements are sized to

            screen_height: The height the elements are sized to
        """
        self._main_window = VBox(min_size=(screen_width, screen_height),
                                 position=(0, 0), hexpand=1, vexpand=1)
        self._main_window.capture(self.key_pressed, "keyPressed")
        self._menubar = MenuBar(min_size=(screen_width, self.MENU_HEIGHT))
        self.init_menu_actions()
        self._main_window.addChild(self._menubar)
        self._toolbar_area = ScrollArea(border_size=1, vexpand=1, hexpand=1,
                                        min_size=(screen_width,
                                                  self.TOOLBAR_HEIGHT),
                                        max_size=(500000,
                                                  self.TOOLBAR_HEIGHT))
        self._toolbar = HBox(vexpand=0, hexpand=1)
        for widget in pychan.WIDGETS:
            button = pychan.Button(text=unicode(widget), max_size=(500000,
                                                          self.TOOLBAR_HEIGHT))
            button.capture(cbwa(self.tool_clicked, widget), "action")
            self._toolbar.addChild(button)
        self._toolbar_area.content = self._toolbar
        self._main_window.addChild(self._toolbar_area)
        self._bottom_window = HBox(border_size=1, vexpand=1, hexpand=1)
        self._edit_wrapper = ScrollArea(border_size=1, vexpand=1, hexpand=3)
        self._edit_window = EditContainer(parent=self._edit_wrapper)
        self._edit_window.capture(self.cb_edit_window_mouse_pressed,
                                  "mousePressed")
        self._edit_window.capture(self.cb_on_widget_selected, "mouseReleased")
        self._edit_window.capture(self.cb_on_edit_window_dragged,
                                  "mouseDragged")

        self._edit_wrapper.addChild(self._edit_window)
        self._bottom_window.addChild(self._edit_wrapper)
        self._right_window = VBox(min_size=(250, 0), max_size=(250, 500000),
                                                         vexpand=1, hexpand=1)
        self._widget_combo = pychan.DropDown(vexpand=1, hexpand=1,
                                             min_size=(250, 20),
                                             max_size=(250, 20))
        self.update_combo()
        self._widget_combo.capture(self.cb_combo_item_selected, "action")
        self._right_window.addChild(self._widget_combo)
        self._property_area = ScrollArea(border_size=1, vexpand=1, hexpand=1)
        self._property_window = VBox(border_size=1, vexpand=1, hexpand=1)
        self._property_area.content = self._property_window
        self._right_window.addChild(self._property_area)
        self._bottom_window.addChild(self._right_window)
        self._main_window.addChild(self._bottom_window)
        self._main_window.show()
        self.clear_gui()

    def init_menu_actions(self):
        """Initialize actions for the menu"""
        open_project_action = Action(_(u"Open"), "gui/icons/open_file.png")
        open_project_action.helptext = _(u"Open GUI file")
        activated.connect(self.cb_on_open_project_action,
                                 sender=open_project_action)
        exit_action = Action(_(u"Exit"), "gui/icons/quit.png")
        exit_action.helptext = _(u"Exit program")
        activated.connect(self.quit, sender=exit_action)
        self._file_menu = Menu(name=_(u"File"))
        self._file_menu.addAction(open_project_action)
        self._file_menu.addSeparator()
        self._file_menu.addAction(exit_action)
        self._menubar.addMenu(self._file_menu)
        self._window_menu = Menu(name=_(u"Guis"))
        self._menubar.addMenu(self._window_menu)

    def get_widget_in(self, widget, x_pos, y_pos):
        """Returns the first child widget at the position in the widgets area

            Args:

                widget: The widget in which area the child is looked for.

                x_pos: The horizontal position where the widget should be
                looked for

                y_pos: The vertical position where the widget should be looked
                for
        """
        point = fife.Point(x_pos, y_pos)
        abs_x, abs_y = self.get_pos_in_scrollarea(widget)
        rect = fife.Rect(abs_x, abs_y,
                         widget.real_widget.getWidth(),
                         widget.real_widget.getHeight())
        if rect.contains(point):
            if hasattr(widget, "children"):
                for child in widget.children:
                    found = self.get_widget_in(child, x_pos, y_pos)
                    if found:
                        return found
                return widget
            elif hasattr(widget, "content") and widget.content is not None:
                found = self.get_widget_in(widget.content, x_pos, y_pos)
                if found:
                    return found
                else:
                    return widget
            else:
                return widget

        return None

    def cb_edit_window_mouse_pressed(self, event, widget):
        """Called when a mouse button is pressed on the edit window

        Args:

            event: A fife.MouseEvent instance

            widget: The edit window
        """
        self._old_x = event.getX()
        self._old_y = event.getY()

    def cb_on_widget_selected(self, event, widget):
        """Called when a mouse buttib is released on a widget

        Args:

            event: A fife.MouseEvent instance

            widget: The widget that was clicked
        """
        if self._widget_dragged:
            self._widget_dragged = False
            return
        if self._marker_dragged:
            # Stops the editor from selecting another widget after a widget has
            # been resized by a marker
            self._marker_dragged = False
            return
        assert isinstance(event, fife.MouseEvent)
        assert isinstance(widget, pychan.Widget)
        real_widget = widget.real_widget
        assert isinstance(real_widget, fife.fifechan.Widget)
        clicked = self.get_widget_in(widget, event.getX(), event.getY())
        if clicked == widget:
            clicked = None
        self.select_widget(clicked)

    def get_pos_in_scrollarea(self, widget):
        """Returns the position of the widget in the scrollarea

        Args:

            widget: The widget
        """
        assert isinstance(widget, pychan.Widget)
        real_widget = widget.real_widget
        assert isinstance(real_widget, fife.fifechan.Widget)
        x_pos, y_pos = real_widget.getAbsolutePosition()
        y_pos -= (self.TOOLBAR_HEIGHT + self.MENU_HEIGHT)
        y_pos += self._edit_wrapper.vertical_scroll_amount
        x_pos += self._edit_wrapper.horizontal_scroll_amount

        return x_pos, y_pos

    def cb_on_marker_dragged(self, event, widget):
        """Called when a marker is being dragged

        Args:

            event: A fife.MouseEvent

            widget: The marker that is  being dragged
        """
        assert isinstance(widget, pychan.Widget)
        old_x, old_y = self.get_pos_in_scrollarea(widget)
        rel_x = event.getX()
        rel_y = event.getY()
        new_x = old_x + rel_x
        new_y = old_y + rel_y
        marker = widget.name[-2:]
        if marker == "TL":
            if new_x >= self._markers["BR"].x:
                return
            if new_y >= self._markers["BR"].y:
                return
            self.selected_widget.x += rel_x
            self.selected_widget.y += rel_y
            self.selected_widget.width += rel_x * -1
            self.selected_widget.height += rel_y * -1
            widget.x += rel_x
            widget.y += rel_y
        if marker == "TR":
            if new_x <= self._markers["BL"].x:
                return
            if new_y >= self._markers["BL"].y:
                return
            self.selected_widget.y += rel_y
            self.selected_widget.width += rel_x
            self.selected_widget.height += rel_y * -1
            widget.x += rel_x
            widget.y += rel_y
        if marker == "BR":
            if new_x <= self._markers["TL"].x:
                return
            if new_y <= self._markers["TL"].y:
                return
            self.selected_widget.width += rel_x
            self.selected_widget.height += rel_y
            widget.x += rel_x
            widget.y += rel_y
        if marker == "BL":
            if new_x >= self._markers["TR"].x:
                return
            if new_y <= self._markers["TR"].y:
                return
            self.selected_widget.x += rel_x
            self.selected_widget.width += rel_x * -1
            self.selected_widget.height += rel_y
            widget.x += rel_x
            widget.y += rel_y
        self.update_editor()

    def cb_on_marker_pressed(self, event, widget):
        """Called when a mouse button was pressed on a marker

        Args:

            event: A fife.MouseEvent

            widget: The marker where the mouse was pressed on
        """
        assert isinstance(event, fife.MouseEvent)
        if event.getButton() == 1:
            self._marker_dragged = True

    def position_markers(self):
        """RePositions the markers on the selected widget"""
        if self.selected_widget is None:
            return
        x_pos, y_pos = self.get_pos_in_scrollarea(self.selected_widget)
        x_pos -= 5
        y_pos -= 5
        self._markers["TL"].position = x_pos, y_pos
        x_pos += self.selected_widget.real_widget.getWidth()
        self._markers["TR"].position = x_pos, y_pos
        y_pos += self.selected_widget.real_widget.getHeight()
        self._markers["BR"].position = x_pos, y_pos
        x_pos -= self.selected_widget.real_widget.getWidth()
        self._markers["BL"].position = x_pos, y_pos

    def recreate_markers(self):
        """ReCreates the markers for the currently selected widget"""
        self.clear_markers()
        if self.selected_widget is not None:
            image_path = os.path.join(self.DATA_PATH, "gui/icons/marker.png")
            marker_tl = pychan.Icon(parent=self._edit_window,
                name="MarkerTL",
                size=(10, 10),
                image=image_path)
            marker_tl.capture(self.cb_on_marker_dragged, "mouseDragged")
            marker_tl.capture(self.cb_on_marker_pressed, "mousePressed")
            self._edit_window.addChild(marker_tl)
            self._markers["TL"] = marker_tl
            marker_tr = pychan.Icon(parent=self._edit_window,
                name="MarkerTR",
                size=(10, 10),
                image=image_path)
            marker_tr.capture(self.cb_on_marker_dragged, "mouseDragged")
            marker_tr.capture(self.cb_on_marker_pressed, "mousePressed")
            self._edit_window.addChild(marker_tr)
            self._markers["TR"] = marker_tr
            marker_br = pychan.Icon(parent=self._edit_window,
                name="MarkerBR",
                size=(10, 10),
                image=image_path)
            marker_br.capture(self.cb_on_marker_dragged, "mouseDragged")
            marker_br.capture(self.cb_on_marker_pressed, "mousePressed")
            self._edit_window.addChild(marker_br)
            self._markers["BR"] = marker_br
            marker_bl = pychan.Icon(parent=self._edit_window,
                name="MarkerBL",
                size=(10, 10),
                image=image_path)
            marker_bl.capture(self.cb_on_marker_dragged, "mouseDragged")
            marker_bl.capture(self.cb_on_marker_pressed, "mousePressed")
            self._edit_window.addChild(marker_bl)
            self._markers["BL"] = marker_bl
        self.update_editor()

    def cb_property_changed(self, attr, widget, property_name, error=False):
        """Called when a property is changed

        Args:

            attr: A fife.extensions.pychan.attrs.Attr instance

            widget: The widget that holds the new value

            property_name: The name of the widget property that contains
            the new value

            error: Reset value if an error was raised
        """
        try:
            value = attr.parse(getattr(widget, property_name))
            setattr(self.selected_widget, attr.name, value)
            self.position_markers()
        except ParserError:
            if error:
                self.update_editor()

    def update_property_window(self):
        """Update the property window"""
        selected = self.selected_widget
        self._property_window.removeAllChildren()
        if selected is None:
            return
        assert isinstance(selected, pychan.Widget)
        for attr in selected.ATTRIBUTES:
            assert isinstance(attr, attrs.Attr)
            property_item = HBox(name=attr.name)
            property_label = pychan.Label(name="label",
                                          text=unicode(attr.name))
            value = getattr(selected, attr.name)
            property_edit = None
            callback = None
            finish_callback = None
            if isinstance(attr, attrs.PointAttr):
                property_edit = pychan.TextField(name="edit",
                                                 text=u"%i, %i" % (value))
                callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text"),
                            "keyPressed")
                finish_callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text", True),
                            "action")
            elif isinstance(attr, attrs.ColorAttr):
                property_edit = pychan.TextField(name="edit",
                                                 text=u"%i, %i, %i, %i" %
                                                 (value.r,
                                                  value.g,
                                                  value.b,
                                                  value.a))
                callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text"),
                            "keyPressed")
                finish_callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text", True),
                            "action")
            elif isinstance(attr, attrs.IntAttr):
                property_edit = pychan.TextField(name="edit",
                                                 text=unicode(value))
                callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text"),
                            "keyPressed")
                finish_callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text", True),
                            "action")
            elif isinstance(attr, attrs.FloatAttr):
                property_edit = pychan.TextField(name="edit",
                                                 text=unicode(value))
                callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text"),
                            "keyPressed")
                finish_callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text", True),
                            "action")
            elif isinstance(attr, attrs.BoolAttr):
                property_edit = pychan.CheckBox(marked=value)
                finish_callback = (cbwa(self.cb_property_changed, attr,
                                                          property_edit,
                                                          "marked"),
                            "mouseClicked")
            else:
                property_edit = pychan.TextField(name="edit",
                                                 text=unicode(value))
                callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text"),
                            "keyPressed")
                finish_callback = (cbwa(self.cb_property_changed, attr,
                                                         property_edit,
                                                         "text", True),
                            "action")
            if callback is not None:
                property_edit.capture(*callback)
            if finish_callback is not None:
                property_edit.capture(*finish_callback)
            property_item.addChildren(property_label)
            property_item.addChildren(property_edit)

            self._property_window.addChildren(property_item)
        self._property_window.adaptLayout()
        self._property_window.show()

    def select_widget(self, widget):
        """Sets a widget to be the currently selected one

        Args:

            widget: The widget
        """
        if widget in self._markers.values():
            return
        if widget is None:
            self._selected_widget = None
            self._widget_combo.selected = -1
        else:
            assert isinstance(widget, pychan.Widget)
            self._selected_widget = widget
            self._widget_combo.selected = self._widgets.index(widget)
        self.recreate_markers()

    def switch_language(self, language):
        """Switch to the given language

        Args:

            language: The name of the language to switch to
        """
        if not language in self.__languages:
            raise KeyError("The language '%s' is not available" % language)
        if not language == self.__current_language:
            self.__languages[language].install()
            self.__current_language = language

    def clear_markers(self):
        """Removes the markers"""
        for marker in self._markers.itervalues():
            self._edit_window.removeChild(marker)
        self._markers = {}

    def clear_gui(self):
        """Clears the current gui file and markers"""
        self.clear_markers()
        self._edit_window.removeAllChildren()
        self.select_widget(None)
        self._widgets = []
        self.update_combo()

    def cb_on_open_project_action(self):
        """Display the filebrowser to selct a gui file to open"""
        browser = FileBrowser(self.engine, self.cb_on_project_file_selected,
                              extensions=["pychan"],
                              guixmlpath=self.FILEBROWSER_XML)
        browser.setDirectory(".")
        browser.showBrowser()

    def cb_on_project_file_selected(self, path, filename):
        """Called when a gui file was selected

        Args:

            path: Path to the selected file

            filename: The selected file
        """
        filepath = os.path.join(path, filename)
        project_file = file(filepath, "r")
        project = yaml.load(project_file)
        gui_path = os.path.join(path, project["settings"]["gui_path"])
        self._current_gui_path = gui_path
        gui_files = project["guis"]
        last_gui = project["settings"]["last_gui"]
        selected_gui_action = None
        self._guis = {}
        self._gui_actions.clear()
        for gui_name, gui_file in gui_files.iteritems():
            real_gui_file = os.path.join(path, gui_file)
            abs_gui_file = os.path.abspath(real_gui_file)
            gui_action = Action(unicode(gui_name), checkable=True)
            gui_action.helptext = _(u"Show %s gui" % (gui_name))
            gui_action.gui_name = gui_name
            self._gui_actions.addAction(gui_action)
            if gui_name == last_gui:
                selected_gui_action = gui_action
            self._guis[gui_name] = abs_gui_file
        self.update_gui_menu()
        if selected_gui_action:
            selected_gui_action.setChecked(True)
        else:
            self.clear_gui()

    def disable_gui(self, widget, recursive=True):
        """Disablds the widget.

        Args:

            widget: The widget to disable

            recursive: Whether to disable the children of the widget, or not.
        """
        widget.real_widget.setEnabled(False)
        if not recursive:
            return
        if hasattr(widget, "children"):
            for child in widget.children:
                self.disable_gui(child, True)
        elif hasattr(widget, "content") and widget.content is not None:
            self.disable_gui(widget.content, True)

    def load_gui(self, filename):
        """Load a gui file and return the gui

        Args:

            filename: The path to the file

        Returns: The loaded gui
        """
        try:
            return pychan.loadXML(filename)
        except IOError:
            self.error_dialog(u"File '%s' was not found." %
                              (filename))
        except SAXParseException:
            self.error_dialog(u"Could not parse XML")
        except GuiXMLError, error:
            self.error_dialog(unicode(error))

    def createListener(self):  # pylint: disable-msg=W0221, C0103
        """Create and return the listener for this application"""
        self._listener = EditorEventListener(self)
        return self._listener

    def update_editor(self):
        """Updates the editor to a change in the selected widget"""
        self.edit_window.resize_to_content()
        self.position_markers()
        self.update_property_window()

    def cb_on_edit_window_dragged(self, event, widget):
        """Called when the edit window is being tried to dragged.
        Drags the selected widget instead.

        Args:

            event: A fife.MouseEvent

            widget: The widget being dragged
        """
        if self._marker_dragged:
            return
        if self.selected_widget is None:
            selected = self.get_widget_in(self.edit_window,
                                        event.getX(),
                                        event.getY())
            if selected is not None and selected is not self._edit_window:
                self.select_widget(selected)
            else:
                return

        rel_x = event.getX() - self._old_x
        rel_y = event.getY() - self._old_y
        self.selected_widget.x += rel_x
        self.selected_widget.y += rel_y
        self.update_editor()
        self._old_x = event.getX()
        self._old_y = event.getY()
        self._widget_dragged = True

    def tool_clicked(self, tool):
        """Called when a tool was clicked"""
        cls = pychan.WIDGETS[tool]
        new_widget = cls(name="New_%s" % tool)
        self.disable_gui(new_widget)
        width = 50
        height = 50
        if self.selected_widget is not None:
            try:
                self.selected_widget.addChild(new_widget)
                new_widget.parent = self.selected_widget
                if self.selected_widget.width < width:
                    width = self.selected_widget.width - 1
                if self.selected_widget.height < height:
                    height = self.selected_widget.height - 1
            except RuntimeError:
                self.error_dialog(_(u"Please select a widget "
                                  u"that can contain children."))
                return
        else:
            self.error_dialog(_(u"Please select a widget "
                              u"that can contain children."))
            return
        new_widget.size = (width, height)
        self.add_widget_to_list(new_widget)
        self.update_combo()
        self._edit_window.show()
        self.select_widget(new_widget)

    def add_widget_to_list(self, widget):
        """Adds a widget and its children to the widget list

        Args:

            widget: The widget to add
        """
        self._widgets.append(WidgetItem(widget))
        if hasattr(widget, "children"):
            for child in widget.children:
                self.add_widget_to_list(child)

    def update_combo(self):
        """Updates the combo box"""
        self._widget_combo.items = self._widgets
        self._widget_combo.show()

    def cb_combo_item_selected(self, event, widget):
        """Called when an item was selected in the combo box

        Args:

            event: A fife.Event

            widget: The combo box
        """
        assert isinstance(widget, pychan.DropDown)
        self.select_widget(widget.selected_item.widget)

    def remove_widget_recursive(self, widget):
        """Removes a widget and all its children

        Args:

            widget: The widget to remove
        """
        self._widgets.remove(widget)
        parent = widget.parent
        parent.removeChild(widget)
        if hasattr(widget, "children"):
            for child in widget.children:
                self.remove_widget_recursive(child)
        if hasattr(widget, "content") and widget.content is not None:
            self.remove_widget_recursive(widget.content)

    def delete_widget(self, widget):
        """Deletes a widget

        Args:

            widget: The widget to delete
        """
        self.remove_widget_recursive(widget)
        self.select_widget(None)
        self.update_combo()
        self.update_property_window()

    def update_gui_menu(self):
        """Updates the gui menu to the current guis"""
        actions = self._gui_actions.getActions()
        self._window_menu.clear()
        for action in actions:
            self._window_menu.addAction(action)

    def cb_select_gui(self):
        """Called when a menu action to select a gui was clicked"""
        action = self._gui_actions.getChecked()
        self.clear_gui()
        if action is None:
            return
        gui_name = action.gui_name
        if not isinstance(self._guis[gui_name], pychan.Widget):
            old_dir = os.getcwd()
            os.chdir(self._current_gui_path)
            self._guis[gui_name] = self.load_gui(self._guis[gui_name])
            os.chdir(old_dir)
        if self._guis[gui_name] is None:
            return
        gui = self._guis[gui_name]
        self.add_widget_to_list(gui)
        self.disable_gui(gui)
        self._edit_window.addChild(gui)
        self._edit_wrapper.content = self._edit_window
        self.update_combo()

    def new_gui(self, name, cls=pychan.Container, **kwargs):
        """Creates a new gui and adds it to the project

        Args:

            name: The name of the gui

            cls: The root widget to be used for the new gui

            kwargs: Additional args passed to the constructor of the widget

        Returns: The menu action for the created gui
        """
        if name in self._guis.keys():
            self.error_dialog(_(u"A Gui with the name %s already exists")
                              % (name))
            return None
        new_gui = cls(name=name, **kwargs)
        if new_gui.width <= 0 and new_gui.height <= 0:
            new_gui.size = (self._edit_window.width, self.edit_window.height)
        self._guis[name] = new_gui
        gui_action = Action(unicode(name), checkable=True)
        gui_action.helptext = _(u"Show %s gui" % (name))
        gui_action.gui_name = name
        self._gui_actions.addAction(gui_action)
        self.update_gui_menu()
        return gui_action
