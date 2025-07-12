#!/usr/bin/env python3

import sys
import threading
import json
import os
import time
from datetime import datetime
from pathlib import Path
import mido
import pyautogui

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QGroupBox,
    QStatusBar,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QMessageBox,
    QCheckBox,
    QLineEdit,
    QTextEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QColor


class MidiListener(QObject):
    message_received = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.port = None
        self.listening = False

    def start_listening(self, port_name):
        if self.listening:
            self.stop_listening()

        try:
            self.port = mido.open_input(port_name)
            self.listening = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
            return True
        except Exception as e:
            return False

    def stop_listening(self):
        self.listening = False
        if self.port:
            self.port.close()
            self.port = None

    def _listen_loop(self):
        while self.listening and self.port:
            try:
                msg = self.port.poll()
                if msg and msg.type != "clock":
                    # Only emit messages with velocity 0 (note-off events)
                    velocity = getattr(msg, "velocity", None)
                    if velocity == 0:
                        msg_data = {
                            "type": msg.type,
                            "channel": getattr(msg, "channel", None),
                            "note": getattr(msg, "note", None),
                            "velocity": velocity,
                            "control": getattr(msg, "control", None),
                            "value": getattr(msg, "value", None),
                            "program": getattr(msg, "program", None),
                            "time": getattr(msg, "time", 0),
                        }
                        self.message_received.emit(msg_data)
            except Exception:
                break


class KeyConfigDialog(QDialog):
    def __init__(self, parent=None, current_keys=""):
        super().__init__(parent)
        self.setWindowTitle("Configure Keys")
        self.setModal(True)
        self.setFixedSize(400, 300)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Enter the keys to send:"))

        # Key input field
        self.key_input = QLineEdit()
        self.key_input.setText(current_keys)
        self.key_input.setPlaceholderText("e.g., ctrl+c, alt+tab, F5, space")
        layout.addWidget(self.key_input)

        # Help text
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setMaximumHeight(150)
        help_text.setPlainText("""Examples:
• ctrl+c (copy)
• ctrl+v (paste)
• alt+tab (switch window)
• F5 (refresh)
• space (spacebar)
• enter (enter key)
• esc (escape)
• up, down, left, right (arrow keys)
• ctrl+shift+t (multiple modifiers)

Separate multiple key combinations with commas:
ctrl+c, ctrl+v""")
        layout.addWidget(help_text)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_keys(self):
        return self.key_input.text().strip()


class TextConfigDialog(QDialog):
    def __init__(self, parent=None, current_text=""):
        super().__init__(parent)
        self.setWindowTitle("Configure Text")
        self.setModal(True)
        self.setFixedSize(400, 250)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Enter the text to type:"))

        # Text input field
        self.text_input = QTextEdit()
        self.text_input.setPlainText(current_text)
        self.text_input.setPlaceholderText("Enter any text to be typed...")
        self.text_input.setMaximumHeight(100)
        layout.addWidget(self.text_input)

        # Help text
        help_text = QLabel(
            "The text will be typed exactly as entered, including line breaks."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(help_text)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_text(self):
        return self.text_input.toPlainText()


class ActionSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Action")
        self.setModal(True)
        self.setFixedSize(300, 200)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Choose an action for this MIDI input:"))

        self.action_list = QListWidget()
        self.actions = [
            "Send Keys",
            "Write Text",
        ]
        self.action_list.addItems(self.actions)
        layout.addWidget(self.action_list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selected_action(self):
        current_item = self.action_list.currentItem()
        if current_item:
            return current_item.text()
        return None


class MidiMacrosApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Midi Macros")
        self.setGeometry(100, 100, 800, 600)
        self.midi_listener = MidiListener()
        self.midi_listener.message_received.connect(self.on_midi_message)
        self.macros = {}
        self.learning_mode = False
        self.test_mode = True  # Default to test mode for safety
        self.config_file = Path.home() / ".midi_macros_config.json"
        self.highlight_timer = QTimer()
        self.highlight_timer.timeout.connect(self.clear_highlight)
        self.last_execution_time = {}  # Track last execution time for debouncing

        # Setup debug logging if DEBUG=true
        self.debug_enabled = os.getenv("DEBUG", "").lower() == "true"
        if self.debug_enabled:
            self.debug_file = Path.home() / ".midi_macros_debug.log"
            # Clear the log file on startup
            with open(self.debug_file, "w") as f:
                f.write(f"MIDI Macros Debug Log - Started at {datetime.now()}\n")
                f.write("=" * 50 + "\n")

        self.load_macros()
        self.setup_ui()
        self.refresh_midi_ports()

    def setup_ui(self):
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Title and status section
        title_section = QHBoxLayout()

        # Title label
        title_label = QLabel("Midi Macros")
        title_font = QFont("Arial", 24, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_section.addWidget(title_label)

        title_section.addStretch()

        # Connection status indicator
        self.connection_status = QLabel("● DISCONNECTED")
        self.connection_status.setStyleSheet(
            "color: red; font-weight: bold; font-size: 14px;"
        )
        title_section.addWidget(self.connection_status)

        # Mode toggle
        self.mode_toggle = QCheckBox("Live Mode")
        self.mode_toggle.setToolTip(
            "Toggle between Test Mode (safe) and Live Mode (executes actions)"
        )
        self.mode_toggle.toggled.connect(self.toggle_mode)
        title_section.addWidget(self.mode_toggle)

        title_widget = QWidget()
        title_widget.setLayout(title_section)
        main_layout.addWidget(title_widget)

        # MIDI Port Selection
        port_group = QGroupBox("MIDI Port Selection")
        port_layout = QHBoxLayout(port_group)

        port_layout.addWidget(QLabel("Input Port:"))
        self.port_combo = QComboBox()
        port_layout.addWidget(self.port_combo)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_midi_ports)
        port_layout.addWidget(self.refresh_button)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        port_layout.addWidget(self.connect_button)

        main_layout.addWidget(port_group)

        # Macro Management
        macro_group = QGroupBox("MIDI Macros")
        macro_layout = QVBoxLayout(macro_group)

        # Add macro button
        add_button_layout = QHBoxLayout()
        self.add_macro_button = QPushButton("+ Add New Macro")
        self.add_macro_button.clicked.connect(self.start_macro_learning)
        self.add_macro_button.setEnabled(False)
        add_button_layout.addWidget(self.add_macro_button)
        add_button_layout.addStretch()
        macro_layout.addLayout(add_button_layout)

        # Macro table
        self.macro_table = QTableWidget()
        self.macro_table.setColumnCount(4)
        self.macro_table.setHorizontalHeaderLabels(
            ["✏️ MIDI Input", "Action", "Edit", "Delete"]
        )
        self.macro_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.macro_table.itemChanged.connect(self.on_macro_name_changed)
        macro_layout.addWidget(self.macro_table)

        main_layout.addWidget(macro_group, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready - Connect to a MIDI port to begin")

        # Update macro table
        self.update_macro_table()

    def refresh_midi_ports(self):
        self.port_combo.clear()
        try:
            input_ports = mido.get_input_names()
            if input_ports:
                self.port_combo.addItems(input_ports)
                self.status_bar.showMessage(
                    f"Found {len(input_ports)} MIDI input port(s)"
                )
            else:
                self.port_combo.addItem("No MIDI ports found")
                self.status_bar.showMessage("No MIDI input ports found")
        except Exception as e:
            self.status_bar.showMessage(f"Error scanning MIDI ports: {str(e)}")

    def toggle_connection(self):
        if not self.midi_listener.listening:
            port_name = self.port_combo.currentText()
            if port_name and port_name != "No MIDI ports found":
                if self.midi_listener.start_listening(port_name):
                    self.connect_button.setText("Disconnect")
                    self.status_bar.showMessage(f"Connected to {port_name}")
                    self.add_macro_button.setEnabled(True)
                    self.update_connection_status(True, port_name)
                else:
                    self.status_bar.showMessage(f"Failed to connect to {port_name}")
        else:
            self.midi_listener.stop_listening()
            self.connect_button.setText("Connect")
            self.status_bar.showMessage("Disconnected from MIDI port")
            self.add_macro_button.setEnabled(False)
            self.learning_mode = False
            self.update_connection_status(False)

    def on_midi_message(self, msg_data):
        # Log all incoming MIDI messages for debugging
        self.log_midi_message(msg_data)

        if self.learning_mode:
            self.handle_learning_message(msg_data)
        else:
            self.execute_macro(msg_data)

    def start_macro_learning(self):
        self.learning_mode = True
        self.add_macro_button.setText("Press a MIDI key/control...")
        self.add_macro_button.setEnabled(False)
        self.status_bar.showMessage(
            "Learning mode: Press a MIDI key or control to assign an action"
        )

    def handle_learning_message(self, msg_data):
        self.learning_mode = False
        self.add_macro_button.setText("+ Add New Macro")
        self.add_macro_button.setEnabled(True)

        # Show action selection dialog
        dialog = ActionSelectionDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            action = dialog.get_selected_action()
            if action:
                midi_key = self.create_midi_key(msg_data)
                default_name = self.format_midi_input(msg_data)

                # Handle action configuration
                action_config = {}
                if action == "Send Keys":
                    key_dialog = KeyConfigDialog(self)
                    if key_dialog.exec() == QDialog.DialogCode.Accepted:
                        keys = key_dialog.get_keys()
                        if keys:
                            action_config["keys"] = keys
                            action_display = f"Send Keys: {keys}"
                        else:
                            self.status_bar.showMessage("Key configuration cancelled")
                            return
                    else:
                        self.status_bar.showMessage("Key configuration cancelled")
                        return
                elif action == "Write Text":
                    text_dialog = TextConfigDialog(self)
                    if text_dialog.exec() == QDialog.DialogCode.Accepted:
                        text = text_dialog.get_text()
                        if text:
                            action_config["text"] = text
                            # Show preview of text (first 30 chars)
                            preview = text[:30] + "..." if len(text) > 30 else text
                            action_display = f"Write Text: {preview}"
                        else:
                            self.status_bar.showMessage("Text configuration cancelled")
                            return
                    else:
                        self.status_bar.showMessage("Text configuration cancelled")
                        return
                else:
                    action_display = action

                self.macros[midi_key] = {
                    "action": action,
                    "action_display": action_display,
                    "action_config": action_config,
                    "msg_data": msg_data,
                    "custom_name": default_name,
                }
                self.save_macros()
                self.update_macro_table()
                self.status_bar.showMessage(
                    f"Macro created: {default_name} -> {action_display}"
                )
        else:
            self.status_bar.showMessage("Macro creation cancelled")

    def create_midi_key(self, msg_data):
        key_parts = [msg_data.get("type", "")]
        if msg_data.get("channel") is not None:
            key_parts.append(f"ch{msg_data['channel']}")
        if msg_data.get("note") is not None:
            key_parts.append(f"note{msg_data['note']}")
        if msg_data.get("control") is not None:
            key_parts.append(f"cc{msg_data['control']}")
        if msg_data.get("program") is not None:
            key_parts.append(f"prog{msg_data['program']}")
        return "_".join(key_parts)

    def format_midi_input(self, msg_data):
        parts = [msg_data.get("type", "unknown").title()]
        if msg_data.get("channel") is not None:
            parts.append(f"Ch.{msg_data['channel']}")
        if msg_data.get("note") is not None:
            parts.append(f"Note {msg_data['note']}")
        if msg_data.get("control") is not None:
            parts.append(f"CC {msg_data['control']}")
        if msg_data.get("program") is not None:
            parts.append(f"Prog {msg_data['program']}")
        return " | ".join(parts)

    def execute_macro(self, msg_data):
        midi_key = self.create_midi_key(msg_data)
        if midi_key in self.macros:
            # Debouncing: check if this macro was executed recently
            current_time = time.time()
            if midi_key in self.last_execution_time:
                time_since_last = current_time - self.last_execution_time[midi_key]
                if time_since_last < 0.5:  # 500ms debounce
                    self.debug_log(f"   DEBOUNCED (too recent: {time_since_last:.2f}s)")
                    return  # Don't execute if too recent

            # Record this execution time
            self.last_execution_time[midi_key] = current_time

            macro = self.macros[midi_key]
            action = macro["action"]
            action_display = macro.get("action_display", action)
            action_config = macro.get("action_config", {})

            if self.test_mode:
                self.status_bar.showMessage(
                    f"TEST MODE - Would execute: {action_display}"
                )
                self.debug_log(f"   TEST MODE: {action_display}")
            else:
                self.status_bar.showMessage(f"LIVE MODE - Executing: {action_display}")
                self.debug_log(f"   EXECUTING: {action_display}")
                self.execute_action(action, action_config)
            self.highlight_macro(midi_key)

    def debug_log(self, message):
        """Write debug message to file if DEBUG=true"""
        if self.debug_enabled:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[
                :-3
            ]  # Include milliseconds
            try:
                with open(self.debug_file, "a") as f:
                    f.write(f"{timestamp} {message}\n")
            except Exception:
                pass  # Silently fail if can't write to debug file

    def log_midi_message(self, msg_data):
        """Log incoming MIDI message for debugging"""
        if not self.debug_enabled:
            return

        # Create a readable log entry for debugging
        log_parts = [f"[{msg_data.get('type', 'unknown')}]"]

        if msg_data.get("channel") is not None:
            log_parts.append(f"Ch:{msg_data['channel']}")
        if msg_data.get("note") is not None:
            log_parts.append(f"Note:{msg_data['note']}")
        if msg_data.get("velocity") is not None:
            log_parts.append(f"Vel:{msg_data['velocity']}")
        if msg_data.get("control") is not None:
            log_parts.append(f"CC:{msg_data['control']}")
        if msg_data.get("value") is not None:
            log_parts.append(f"Val:{msg_data['value']}")
        if msg_data.get("program") is not None:
            log_parts.append(f"Prog:{msg_data['program']}")

        # Check if this message has a macro
        midi_key = self.create_midi_key(msg_data)
        has_macro = midi_key in self.macros
        macro_status = " -> HAS MACRO" if has_macro else ""

        log_entry = " ".join(log_parts) + macro_status
        self.debug_log(log_entry)

    def execute_action(self, action, config):
        try:
            if action == "Send Keys":
                keys = config.get("keys", "")
                if keys:
                    # Parse and send multiple key combinations
                    key_combinations = [k.strip() for k in keys.split(",")]
                    for key_combo in key_combinations:
                        if key_combo:
                            pyautogui.hotkey(*key_combo.split("+"))
            elif action == "Write Text":
                text = config.get("text", "")
                if text:
                    pyautogui.write(text)
        except Exception as e:
            self.status_bar.showMessage(f"Error executing action: {str(e)}")

    def update_macro_table(self):
        self.macro_table.setRowCount(len(self.macros))
        for row, (midi_key, macro) in enumerate(self.macros.items()):
            # MIDI Input column (editable)
            custom_name = macro.get(
                "custom_name", self.format_midi_input(macro["msg_data"])
            )
            name_item = QTableWidgetItem(custom_name)
            name_item.setData(
                Qt.ItemDataRole.UserRole, midi_key
            )  # Store the key for identification
            self.macro_table.setItem(row, 0, name_item)

            # Action column (read-only)
            action_display = macro.get("action_display", macro["action"])
            action_item = QTableWidgetItem(action_display)
            action_item.setFlags(action_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.macro_table.setItem(row, 1, action_item)

            # Edit button
            edit_button = QPushButton("Edit")
            edit_button.clicked.connect(
                lambda checked, key=midi_key: self.edit_macro(key)
            )
            self.macro_table.setCellWidget(row, 2, edit_button)

            # Delete button
            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(
                lambda checked, key=midi_key: self.delete_macro(key)
            )
            self.macro_table.setCellWidget(row, 3, delete_button)

    def edit_macro(self, midi_key):
        if midi_key in self.macros:
            macro = self.macros[midi_key]
            action = macro["action"]
            action_config = macro.get("action_config", {})

            if action == "Send Keys":
                current_keys = action_config.get("keys", "")
                key_dialog = KeyConfigDialog(self, current_keys)
                if key_dialog.exec() == QDialog.DialogCode.Accepted:
                    new_keys = key_dialog.get_keys()
                    if new_keys:
                        macro["action_config"]["keys"] = new_keys
                        macro["action_display"] = f"Send Keys: {new_keys}"
                        self.save_macros()
                        self.update_macro_table()
                        self.status_bar.showMessage("Macro updated")
            elif action == "Write Text":
                current_text = action_config.get("text", "")
                text_dialog = TextConfigDialog(self, current_text)
                if text_dialog.exec() == QDialog.DialogCode.Accepted:
                    new_text = text_dialog.get_text()
                    if new_text:
                        macro["action_config"]["text"] = new_text
                        # Show preview of text (first 30 chars)
                        preview = (
                            new_text[:30] + "..." if len(new_text) > 30 else new_text
                        )
                        macro["action_display"] = f"Write Text: {preview}"
                        self.save_macros()
                        self.update_macro_table()
                        self.status_bar.showMessage("Macro updated")
            else:
                self.status_bar.showMessage(f"Editing not yet supported for {action}")

    def delete_macro(self, midi_key):
        if midi_key in self.macros:
            del self.macros[midi_key]
            self.save_macros()
            self.update_macro_table()
            self.status_bar.showMessage("Macro deleted")

    def load_macros(self):
        try:
            if self.config_file.exists():
                with open(self.config_file, "r") as f:
                    self.macros = json.load(f)
        except Exception as e:
            self.macros = {}

    def save_macros(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.macros, f, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save macros: {str(e)}")

    def on_macro_name_changed(self, item):
        # Only handle changes to column 0 (MIDI Input names)
        if item.column() == 0:
            midi_key = item.data(Qt.ItemDataRole.UserRole)
            if midi_key and midi_key in self.macros:
                self.macros[midi_key]["custom_name"] = item.text()
                self.save_macros()

    def highlight_macro(self, midi_key):
        # Find the row with this midi_key and highlight it
        for row in range(self.macro_table.rowCount()):
            item = self.macro_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == midi_key:
                # Set background color to light green
                for col in range(self.macro_table.columnCount()):
                    table_item = self.macro_table.item(row, col)
                    if table_item:
                        table_item.setBackground(QColor(144, 238, 144))  # Light green

                # Start timer to clear highlight after 500ms
                self.highlight_timer.stop()
                self.highlighted_row = row
                self.highlight_timer.start(500)
                break

    def clear_highlight(self):
        # Clear highlighting from the previously highlighted row
        if hasattr(self, "highlighted_row"):
            for col in range(self.macro_table.columnCount()):
                item = self.macro_table.item(self.highlighted_row, col)
                if item:
                    item.setBackground(QColor())  # Default background
        self.highlight_timer.stop()

    def toggle_mode(self, checked):
        self.test_mode = not checked
        mode_text = "LIVE MODE" if not self.test_mode else "TEST MODE"
        self.status_bar.showMessage(f"Switched to {mode_text}")

    def update_connection_status(self, connected, port_name=None):
        if connected:
            self.connection_status.setText(f"● CONNECTED ({port_name})")
            self.connection_status.setStyleSheet(
                "color: green; font-weight: bold; font-size: 14px;"
            )
        else:
            self.connection_status.setText("● DISCONNECTED")
            self.connection_status.setStyleSheet(
                "color: red; font-weight: bold; font-size: 14px;"
            )

    def closeEvent(self, event):
        self.midi_listener.stop_listening()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MidiMacrosApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
