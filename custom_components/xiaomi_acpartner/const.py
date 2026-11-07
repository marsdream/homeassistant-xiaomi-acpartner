"""Constants for the Xiaomi Air Conditioning Companion integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "xiaomi_acpartner"

CONF_NAME = "name"
CONF_TOKEN = "token"

# Fixed slot used for user-uploaded (TTS / VOD) audio.
USER_MUSIC_ID = 99999

# Fixed slot used for infrared learning by default.
DEFAULT_IR_SLOT = 30

# MiIO method names, see the MiIO protocol documentation.
METHOD_STATUS = "get_model_and_state"
METHOD_FM_STATUS = "get_prop_fm"
METHOD_CHANNELS = "get_channels"
METHOD_MUSIC_SPACE = "get_music_free_space"
METHOD_MUSIC_INFO = "get_music_info"
METHOD_DOWNLOAD_PROGRESS = "get_download_progress"
METHOD_FM_PLAY = "play_fm"
METHOD_FM_PLAY_SPECIFY = "play_specify_fm"
METHOD_FM_VOLUME = "volume_ctrl_fm"
METHOD_PLAY_MUSIC = "play_music"
METHOD_PLAY_MUSIC_NEW = "play_music_new"
METHOD_DOWNLOAD_USER_MUSIC = "download_user_music"
METHOD_DELETE_USER_MUSIC = "delete_user_music"
METHOD_IR_LEARN_START = "start_ir_learn"
METHOD_IR_LEARN_STOP = "end_ir_learn"
METHOD_IR_LEARN_RESULT = "get_ir_learn_result"
METHOD_SEND_IR_CODE = "send_ir_code"
METHOD_SEND_CMD = "send_cmd"

# MiIO method names, see the MiIO protocol documentation.
RINGTONE_TYPES = {
    "alarm": 0,
    "clock": 1,
    "chord": 2,
    "custom": 3,
}

SCAN_INTERVAL = timedelta(seconds=30)

# The device is single core and every MiIO call interrupts its audio stream,
# so the expensive lists are refreshed far less often than the radio status.
SLOW_REFRESH_INTERVAL = 600

# The device stores the current radio volume as an integer 0-100.
VOLUME_MIN = 0
VOLUME_MAX = 100

# The device stores the uploaded file as-is, so a large file eats into its
# ~11 MB of free space. Keep the uploads small and leave a safety margin.
MAX_UPLOAD_BYTES = 512 * 1024

# Refuse to upload when the remaining space would drop below this margin.
MIN_FREE_SPACE = 2 * 1024 * 1024

# Text to speech.
#
# The Microsoft Edge voices are used by default. They are free and need no
# account, so the integration works out of the box. A hosted service can be
# used as a fallback, its address and API key are configured in the options
# of the integration.
TTS_DEFAULT_SPEAKER = "zh-CN-XiaoxiaoNeural"
TTS_FOLDER = "xiaomi_acpartner"

# Keep the spoken text short, a long message would fill up the device.
TTS_MAX_CHARS = 300

# Keep only the last few renderings on disk, they are cheap to recreate.
TTS_MAX_CACHE_FILES = 5

# Extra seconds to wait after the measured length of the audio. The device
# starts playing a moment after the command and the last syllable needs a
# little more time, the file may only be deleted after that.
PLAYBACK_MARGIN = 3

# Bump this whenever the rendering or the conversion changes. It is part of
# the cache name, so old files are not reused after a change.
TTS_PIPELINE_VERSION = 2

# Optional settings for a hosted text to speech service, used as a fallback
# when the Edge voices are not available.
CONF_TTS_API_KEY = "tts_api_key"
CONF_TTS_API_URL = "tts_api_url"

# Address the device can use to download the rendered audio.
CONF_TTS_BASE_URL = "tts_base_url"
