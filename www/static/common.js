function niceduration(duration) {
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

function display_timestamp(node) {
	var timestamp = new Date(node.data('timestamp') * 1000);
	node.text(timestamp.toLocaleString());
}

function display_timeonly(node) {
	var timestamp = new Date(node.data('timestamp') * 1000);
	node.text(timestamp.toLocaleTimeString());
}

function display_duration(node) {
	var timestamp = new Date(node.data('timestamp') * 1000);
	node.text(niceduration((Date.now() - timestamp) / 1000));
	node.attr('title', timestamp.toLocaleString());
}

$(function(){
	$(".timestamp").each(function(){
		display_timestamp($(this));
	});
	$(".timestamp-time").each(function(){
		display_timeonly($(this));
	});
	$(".timestamp-duration").each(function(){
		display_duration($(this));
	});
});
