enum sensor_mode {
    SENSOR_MODE_OFF,
    SENSOR_MODE_ON,
};

enum sensor_mode toggle_mode(enum sensor_mode current) {
    switch (current) {
    case SENSOR_MODE_OFF:
        return SENSOR_MODE_ON;
    case SENSOR_MODE_ON:
    default:
        return SENSOR_MODE_OFF;
    }
}
