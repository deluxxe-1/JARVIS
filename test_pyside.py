import sys
from PySide6.QtWidgets import QApplication, QLabel

def main() -> int:
    app = QApplication(sys.argv)
    label = QLabel("Hello World")
    label.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
