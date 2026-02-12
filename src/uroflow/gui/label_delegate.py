"""Custom delegate for label dropdown in event table."""

from PySide6.QtWidgets import QStyledItemDelegate, QComboBox
from PySide6.QtCore import Qt


class LabelDelegate(QStyledItemDelegate):
    """Delegate to provide dropdown for event label selection."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = ["", "urine", "feces", "bad"]
        self.label_display = {
            "": "Unlabeled",
            "urine": "Urine",
            "feces": "Feces",
            "bad": "Bad"
        }
    
    def createEditor(self, parent, option, index):
        """Create combo box editor.
        
        Args:
            parent: Parent widget
            option: Style option
            index: Model index
            
        Returns:
            QComboBox editor
        """
        editor = QComboBox(parent)
        
        # Add items with display names
        for label in self.labels:
            display_name = self.label_display.get(label, label)
            editor.addItem(display_name, label)  # Display name, user data = actual value
        
        return editor
    
    def setEditorData(self, editor, index):
        """Set current value in editor.
        
        Args:
            editor: QComboBox editor
            index: Model index
        """
        # Get current label value
        current_value = index.model().data(index, Qt.EditRole)
        if current_value is None:
            current_value = ""
        
        # Find and set index
        for i in range(editor.count()):
            if editor.itemData(i) == current_value:
                editor.setCurrentIndex(i)
                break
    
    def setModelData(self, editor, model, index):
        """Save editor value to model.
        
        Args:
            editor: QComboBox editor
            model: Table model
            index: Model index
        """
        # Get selected label value (user data)
        value = editor.currentData()
        model.setData(index, value, Qt.EditRole)
    
    def updateEditorGeometry(self, editor, option, index):
        """Update editor geometry.
        
        Args:
            editor: Editor widget
            option: Style option
            index: Model index
        """
        editor.setGeometry(option.rect)
