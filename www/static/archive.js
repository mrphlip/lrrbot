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
		window.chatlines.push({ts: Number($(this).data("timestamp")), obj: $(this)});
	});

	// Create poll to scroll the chat to the right place
	window.player = document.getElementById("clip_embed_player_flash");
	window.lasttime = -1;
	setInterval(doScroll, 1000);

	// Pause/play video with spacebar
	$(window).keypress(function(e){
		if (e.keyCode === 0 || e.keyCode === 32) {
			if (window.player.isPaused())
				window.player.playVideo();
			else
				window.player.pauseVideo();
			e.preventDefault();
		}
	});

	// just in case the videoPlaying event somehow happens before the init function runs
	if (window.videoLoaded) {
		window.videoLoaded = false;
		onPlayerEvent({event: "videoPlaying", data: {}});
	}
});

function getVideoTime() {
	if (!window.player)
		return -1;
	else if (typeof window.player.getVideoTime == "function")
		return window.player.getVideoTime();
	else if (typeof window.player.getVideoTime == "number")
		return window.player.getVideoTime;
	else
		return -1;
}

function doScroll() {
	if (!window.scrollenable)
		return;

	var time = getVideoTime();
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

function onPlayerEvents(data) {
	data.forEach(onPlayerEvent);
}
function onPlayerEvent(e) {
	if (e.event === "videoPlaying") {
		if (window.videoLoaded)
			return;
		window.videoLoaded = true;

		if (!window.player)
			return;

		// When playing starts for the first time, make sure we're at the actual time we wanted
		// Sometimes, depending on what version of the player we have, the "initial_time" param doesn't work
		var time = getVideoTime();
		// If we're off from the specified initial time by more than, say, 10 seconds, jump to the right time
		if (window.initial_time && Math.abs(window.initial_time - time) > 10) {
			window.player.videoSeek(window.initial_time);
		}
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

// This (currently, in the browsers I have tested it on) fools the Twitch player into thinking it's playing on the real Twitch site
// so it doesn't make it so that clicking the player takes you to the Twitch page
window.parent = {location: {hostname: 'www.twitch.tv', search: 'force_embed=1'}};

window.videoLoaded = false;
