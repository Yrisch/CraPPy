import os

# Qt tests draw offscreen: no window pops up, works without a display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
