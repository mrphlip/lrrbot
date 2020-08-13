$(function(){
	// Resize handling from https://github.com/jcubic/jquery.splitter/issues/32#issuecomment-65424376
	var splitPosition = 80;
	var splitter = $("#content").split({
		orientation:"vertical",
		limit:50,
		position: splitPosition + "%",
		onDragEnd: function(){
			splitPosition = Math.round(splitter.position() / splitter.width() * 100);
		},
	});
	$(window).resize(function(){
		splitter.position(splitPosition + "%");
	});

	// Show the timestamps in the local timezone, if that's what the user wants
	var fmt = {hour: "numeric", minute: "numeric", hour12: !window.twentyfour};
	if (window.seconds)
		fmt.second = "numeric";
	$(".timestamp-time").each(function(){
		var timestamp = new Date($(this).data('timestamp') * 1000);
		$(this).text(timestamp.toLocaleTimeString(undefined, fmt));
	});

	// Load the video
	window.player = new Twitch.Player("video", {
		width: "100%",
		height: "100%",
		video: window.video,
	});
	window.player.addEventListener(Twitch.Player.PLAY, onPlayerPlay);

	// Only scroll the chat vertically
	$("#chat").parent().css("overflow-x", "hidden");

	// Allow showing deleted messages
	$(".deleted").click(function(){
		$(this).hide().next(".message").show();
	});

	// Stop scrolling automatically if the user scrolls manually
	$("#chat").parent().scroll(stopScrolling);
	$("#resetscroll").click(startScrolling);
	window.scrollenable = true;

	// Prepare timestamp lookup table
	window.chatlines = [];
	$(".line").each(function(){
		var linediv = $(this).closest(".line-wrapper");
		if (!linediv.length)
			linediv = $(this);
		window.chatlines.push({ts: Number($(this).data("timestamp")), obj: linediv});
	});

	// Create poll to scroll the chat to the right place
	window.lasttime = -1;
	setInterval(doScroll, 1000);

	// Pause/play video with spacebar
	$(window).keypress(onKeypress);
});

function doScroll() {
	if (!window.scrollenable)
		return;

	var time = window.player.getCurrentTime();
	if (time < 0)
		return;

	// Don't scroll if we're stuck at the same time (if the video is paused)
	if (time == window.lasttime)
		return;
	window.lasttime = time;

	scrollChatTo(time + window.start);
}

function scrollChatTo(time) {
	// Binary search to find the first line that is after the current time
	var min = 0;
	var max = window.chatlines.length;
	while (min < max) {
		var mid = (min + max) >> 1;
		if (window.chatlines[mid].ts < time)
			min = mid + 1;
		else
			max = mid;
	}

	// Scroll the chat pane so that this line is below the bottom
	var line;
	if (min < window.chatlines.length) {
		line = window.chatlines[min].obj;
	} else {
		line = $("#chatbottom");
	}
	window.autoscroll = true;
	var chatPane = $("#chat").parent();
	chatPane.scrollTop(chatPane.scrollTop() + line.position().top - chatPane.height());
}

function onPlayerPlay() {
	if (window.initial_time) {
		window.player.seek(window.initial_time);
		window.initial_time = false;
	}
}

function stopScrolling() {
	// don't trigger off our own scrolling
	if (window.autoscroll) {
		window.autoscroll = false;
		return;
	}
	window.scrollenable = false;
	$("#resetscroll").show();
}
function startScrolling() {
	window.scrollenable = true;
	$("#resetscroll").hide();
	doScroll();
}

function onKeypress(e) {
	if (e.key === " " || e.key === "Spacebar" || e.keyCode === 32) {
		if (window.player.isPaused())
			window.player.play();
		else
			window.player.pause();
		e.preventDefault();
	}
}
