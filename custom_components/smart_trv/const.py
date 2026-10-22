"""Constants for Smart TRV."""

DOMAIN = "smart_trv"

CONF_ROOM_SENSOR = "room_sensor"
CONF_TRVS = "trvs"
CONF_WINDOWS = "windows"
CONF_KP = "kp"
CONF_KI = "ki"
CONF_MAX_BOOST = "max_boost"
CONF_MAX_CUT = "max_cut"
CONF_INTERVAL = "interval"
CONF_TRV_STEP = "trv_step"
CONF_NIGHT_ENTITY = "night_entity"  # schedule/input_boolean/binary_sensor: on = night

DEFAULT_NAME = "Smart TRV"
DEFAULT_KP = 3.0  # °C extra TRV setpoint per °C room error
DEFAULT_KI = 1.0  # °C per (°C error * hour)
DEFAULT_MAX_BOOST = 6.0  # max °C the TRV setpoint may sit above the room target
DEFAULT_MAX_CUT = 3.0  # max °C the TRV setpoint may sit below the room target
DEFAULT_INTERVAL = 5  # minutes between control runs
DEFAULT_TRV_STEP = 0.5  # TV02 only accepts 0.5 °C steps

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
