$(function(){
	$("#content").split({orientation:"vertical", limit:50, position: "80%"});

	// Only scroll the chat vertically
	$("#chat").parent().css("overflow-x", "hidden");

	// Allow showing deleted messages
	$(".deleted").click(function(){
		$(this).hide().next(".message").show();
	});

	// Prepare timestamp lookup table
	window.chatlines = [];
	$(".line").each(function(){
		window.chatlines.push({ts: Number($(this).data("timestamp")), obj: $(this)});
	});

	// Create poll to scroll the chat to the right place
	window.player = document.getElementById("clip_embed_player_flash");
	window.lasttime = -1;
	setInterval(doScroll, 1000);
});

function doScroll() {
	var time;
	if (typeof window.player.getVideoTime == "function")
		time = window.player.getVideoTime();
	else if (typeof window.player.getVideoTime == "number")
		time = window.player.getVideoTime;
	else
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
	var line = window.chatlines[min].obj;
	var chatPane = $("#chat").parent();
	chatPane.scrollTop(chatPane.scrollTop() + line.position().top - chatPane.height());
}
