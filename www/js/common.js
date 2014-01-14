function niceduration(duration)
{
	// Should match the code in utils.niceduration in the Python side
	if (duration < 0)
		return "-" + niceduration(-duration);
	duration = Math.floor(duration);
	if (duration < 60)
		return duration + "s";
	duration = Math.floor(duration / 60);
	if (duration < 60)
		return duration + "m";
	duration = Math.floor(duration / 60);
	if (duration < 24)
		return duration + "h";
	return Math.floor(duration / 24) + "d, " + (duration % 24) + "h";
}
