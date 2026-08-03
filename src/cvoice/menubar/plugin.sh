#!/bin/bash
# SwiftBar plugin. All logic lives in `cvoice menubar`; this only calls it.
#
# <xbar.title>cvoice</xbar.title>
# <xbar.desc>Claude Code reporting: banners, speech, history</xbar.desc>

exec "$HOME/.cvoice/bin/cv-hook" menubar
