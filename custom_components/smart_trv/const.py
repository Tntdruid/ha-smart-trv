"""Constants for Smart TRV."""

DOMAIN = "smart_trv"

CONF_ROOM_SENSOR = "room_sensor"
CONF_TRVS = "trvs"
CONF_WINDOWS = "windows"
CONF_KP = "kp"
CONF_KI = "ki"
CONF_NIGHT_ENTITY = "night_entity"  # schedule/input_boolean/binary_sensor: on = night
CONF_WINDOW_OPEN_DELAY = "window_open_delay"  # seconds open before the TRVs turn off
CONF_WINDOW_CLOSE_DELAY = "window_close_delay"  # seconds closed before heating resumes
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_OUTDOOR_GAIN = "outdoor_gain"  # TRV °C per °C between room target and outdoors
CONF_AUTO_TUNE = "auto_tune"
CONF_PREHEAT = "preheat"

DEFAULT_NAME = "Smart TRV"
DEFAULT_KP = 3.0  # °C extra TRV setpoint per °C room error
DEFAULT_KI = 1.0  # °C per (°C error * hour)
DEFAULT_MAX_BOOST = 6.0  # max °C the TRV setpoint may sit above the room target
DEFAULT_MAX_CUT = 3.0  # max °C the TRV setpoint may sit below the room target
DEFAULT_INTERVAL = 5  # minutes between control runs
DEFAULT_TRV_STEP = 0.5  # when the TRV doesn't report target_temp_step (TV02 takes 0.5 °C)
DEFAULT_WINDOW_OPEN_DELAY = 60  # walking through a door should not turn the heating off
DEFAULT_WINDOW_CLOSE_DELAY = 0
DEFAULT_OUTDOOR_GAIN = 0.1
DEFAULT_AUTO_TUNE = True
DEFAULT_PREHEAT = True

# A TRV that hasn't reported for this long, or whose battery is this low, is a problem.
TRV_STALE_HOURS = 6
BATTERY_LOW = 20

TRV_MIN_TEMP = 5.0
TRV_MAX_TEMP = 30.0

ATTR_INTEGRAL = "pi_integral"
ATTR_ERROR = "pi_error"
ATTR_TRV_SETPOINT = "trv_setpoint"
ATTR_WINDOW_OPEN = "window_open"

SIGNAL_UPDATE = "smart_trv_update_{}"  # controller ran -> sensors refresh
SIGNAL_SETTINGS = "smart_trv_settings_{}"  # night temperature changed -> climate and number refresh

STATUS_HEATING = "heating"
STATUS_IDLE = "idle"
STATUS_WINDOW = "window_open"
STATUS_OFF = "off"
STATUS_NO_SENSOR = "no_sensor"
STATUSES = [STATUS_HEATING, STATUS_IDLE, STATUS_WINDOW, STATUS_OFF, STATUS_NO_SENSOR]
