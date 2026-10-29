# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

import os

# Qt tests draw offscreen: no window pops up, works without a display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
