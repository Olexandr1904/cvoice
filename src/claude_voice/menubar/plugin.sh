#!/bin/bash
# SwiftBar plugin. All logic lives in `claude-voice menubar`; this only calls it.
#
# <xbar.title>Claude voice</xbar.title>
# <xbar.desc>Claude Code reporting: banners, speech, history</xbar.desc>

exec "$HOME/.claude-voice/bin/cv-hook" menubar
