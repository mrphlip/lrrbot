window.addEventListener('DOMContentLoaded', function (event) {
	window.original_title = document.title;

	var events = document.querySelectorAll('#notificationlist li');
	for (var i = 0; i < events.length; i++) {
		var event = events[i];
		event.querySelector(".duration").setAttribute('title', new Date(event.dataset.timestamp).toLocaleString());
	}

	if (window.EventSource) {
		var stream = new EventSource(window.EVENTSERVER_ROOT + "/notifications/events?last-event-id=" + window.last_event_id);
		stream.addEventListener("twitch-subscription", function (event) {
			twitch_subscription(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("twitch-resubscription", function (event) {
			twitch_resubscription(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("twitch-message", function (event) {
			twitch_message(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("patreon-pledge", function (event) {
			patreon_pledge(JSON.parse(event.data));
			update_title();
		});
	} else {
		window.setInterval(ajax_poll, 60 * 1000);
	}
	window.setInterval(update_dates, 10 * 1000);
})

function ajax_poll() {
	var req = new XMLHttpRequest();
	req.addEventListener('load', function (event) {
		var events = JSON.parse(req.responseText);
		events.events.forEach(function (event) {
			switch (event.event) {
				case 'twitch-subscription':
					twitch_subscription(event.data);
					break;
				case 'twitch-resubscription':
					twitch_resubscription(event.data);
					break;
				case 'twitch-message':
					twitch_message(event.data);
					break;
				case 'patreon-pledge':
					patreon_pledge(event.data);
					break;
			}
			if (event.id > window.last_event_id) {
				window.last_event_id = event.id;
			}
		});
		update_title();
	})
	req.open("GET", window.EVENTSERVER_ROOT + "/notifications/events?last-event-id=" + window.last_event_id);
	req.setRequestHeader("Accept", "application/json");
	req.send();
}

/* For how long to keep events on the page */
window.MAXIMUM_AGE = 2 * 24 * 60 * 60;

function update_dates() {
	var rows = document.querySelectorAll("#notificationlist li");
	for (var i = 0; i < rows.length; i++) {
		var row = rows[i];
		var duration = (Date.now() - Date.parse(row.dataset.timestamp)) / 1000;
		if (duration > window.MAXIMUM_AGE) {
			row.parentNode.removeChild(row);
		} else {
			row.querySelector(".duration").textContent = niceduration(duration);
		}
	}

	update_title();
}

function update_title() {
	var count = document.querySelectorAll("#notificationlist .new").length;
	if (count > 0) {
		document.title = "(" + count + ") " + window.original_title;
	} else {
		document.title = window.original_title;
	}
}

/* Next row is even or odd */
window.even = false;

function createElementWithClass(element, className) {
	var elem = document.createElement(element);
	elem.className = className;
	return elem;
}

function create_row(data, callback) {
	var row = document.createElement("li");
	row.dataset.timestamp = data.time;
	if (window.even) {
		row.className = "even new";
	} else {
		row.className = "odd new";
	}
	row.addEventListener("click", function (event) {
		this.classList.remove("new");
		update_title();
	})
	window.even = !window.even;

	var list = document.getElementById("notificationlist");
	list.insertBefore(row, list.firstChild);

	var duration = createElementWithClass("div", "duration");
	duration.appendChild(document.createTextNode(niceduration((Date.now() - Date.parse(data.time)) / 1000)));
	row.appendChild(duration);

	var container = createElementWithClass("div", "container");
	row.appendChild(container);

	callback(container);

	var clear = document.createElement("div");
	clear.className = "clear";
	container.appendChild(clear);
}

function twitch_subscription(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		var link = document.createElement("a");
		link.href = "https://www.twitch.tv/" + data.name;
		link.rel = "noopener nofollow";

		if (data.avatar) {
			var avatar_link = link.cloneNode();
			user.appendChild(avatar_link);

			var avatar = document.createElement("img");
			avatar.src = data.avatar;
			avatar_link.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		link.appendChild(document.createTextNode(data.name));
		message.appendChild(link);
		message.appendChild(document.createTextNode(" just subscribed!"));
		message_container.appendChild(message);
	});
}

function twitch_resubscription(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		var link = document.createElement("a");
		link.href = "https://www.twitch.tv/" + data.name;
		link.rel = "noopener nofollow";

		if (data.avatar) {
			var avatar_link = link.cloneNode();
			user.appendChild(avatar_link);

			var avatar = document.createElement("img");
			avatar.src = data.avatar;
			avatar_link.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		link.appendChild(document.createTextNode(data.name));
		message.appendChild(link);
		message.appendChild(document.createTextNode(" subscribed for " + data.monthcount + " month" + (data.monthcount != 1 ? 's' : '') + " in a row!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			quote.appendChild(document.createTextNode(data.message));
			user_message.appendChild(quote);
		}
	});
}

function twitch_message(data) {
	create_row(data, function (container) {
		var message = createElementWithClass("div", "message");
		message.appendChild(document.createTextNode(data.message));
		container.appendChild(message);
	});
}

function patreon_pledge(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.patreon.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		var link = document.createElement("a");
		link.href = data.patreon.url;
		link.rel = "noopener nofollow";

		if (data.avatar) {
			var avatar_link = link.cloneNode();
			user.appendChild(avatar_link);

			var avatar = document.createElement("img");
			avatar.src = data.patreon.avatar;
			avatar_link.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		link.appendChild(document.createTextNode(data.twitch ? data.twitch.name : data.patreon.full_name));
		message.appendChild(link);
		message.appendChild(document.createTextNode(" is now supporting " + window.PATREON_CREATOR_NAME + " on Patreon!"));
		message_container.appendChild(message);
	});
}
