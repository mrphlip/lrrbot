window.addEventListener('DOMContentLoaded', function (event) {
	window.original_title = document.title;

	if (window.EventSource) {
		var stream = new EventSource("/api/v2/events?last-event-id=" + window.last_event_id);
		stream.addEventListener("twitch-subscription", function (event) {
			twitch_subscription(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("twitch-resubscription", function (event) {
			twitch_resubscription(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("twitch-subscription-mysterygift", function (event) {
			twitch_subscription_mysterygift(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("twitch-cheer", function (event) {
			twitch_cheer(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("twitch-raid", function (event) {
			twitch_raid(JSON.parse(event.data));
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
		stream.addEventListener("youtube-membership", function (event) {
			youtube_membership(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("youtube-membership-milestone", function (event) {
			youtube_membership_milestone(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("youtube-membership-gift", function (event) {
			youtube_membership_gift(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("youtube-super-chat", function (event) {
			youtube_super_chat(JSON.parse(event.data));
			update_title();
		});
		stream.addEventListener("youtube-super-sticker", function (event) {
			youtube_super_sticker(JSON.parse(event.data));
			update_title();
		});
	} else {
		window.setInterval(ajax_poll, 60 * 1000);
	}
	window.setInterval(update_dates, 10 * 1000);

	document.getElementById("milestoneshow").addEventListener("click", function (event) {
		var table = document.getElementById("milestonetable");
		if (table.style.display === "block")
			table.style.display = "none";
		else
			table.style.display = "block";
	})
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
				case 'twitch-subscription-mysterygift':
					twitch_subscription_mysterygift(event.data);
					break;
				case 'twitch-raid':
					twitch_raid(event.data);
					break;
				case 'twitch-message':
					twitch_message(event.data);
					break;
				case 'patreon-pledge':
					patreon_pledge(event.data);
					break;
				case "youtube-membership":
					youtube_membership(event.data);
					break;
				case "youtube-membership-milestone":
					youtube_membership_milestone(event.data);
					break;
				case "youtube-membership-gift":
					youtube_membership_gift(event.data);
					break;
				case "youtube-super-chat":
					youtube_super_chat(event.data);
					break;
				case "youtube-super-sticker":
					youtube_super_sticker(event.data);
					break;
			}
			if (event.id > window.last_event_id) {
				window.last_event_id = event.id;
			}
		});
		update_title();
	})
	req.open("GET", "/api/v2/events?last-event-id=" + window.last_event_id);
	req.setRequestHeader("Accept", "application/json");
	req.send();
}

/* For how long to keep events on the page */
window.MAXIMUM_AGE = 2 * 24 * 60 * 60;

function update_dates() {
	var nodes = document.querySelectorAll("#notificationlist li .timestamp-duration");
	for (var i = 0; i < nodes.length; i++) {
		var node = nodes[i];
		var duration = (Date.now() - new Date(node.dataset.timestamp * 1000)) / 1000;
		if (duration > window.MAXIMUM_AGE) {
			node.parentNode.parentNode.removeChild(node.parentNode);
		} else {
			node.textContent = niceduration(duration);
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

	var duration = createElementWithClass("div", "timestamp-duration");
	duration.dataset.timestamp = Date.parse(data.time) / 1000;
	display_duration($(duration));
	row.appendChild(duration);

	var container = createElementWithClass("div", "container");
	row.appendChild(container);

	callback(container);
}

function twitch_subscription(data) {
	if (data.ismulti)
		return;
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" just subscribed"));
		if (data.benefactor)
			message.appendChild(document.createTextNode(", thanks to " + data.benefactor));
		message.appendChild(document.createTextNode("!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}

function twitch_resubscription(data) {
	if (data.ismulti)
		return;
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" subscribed for " + data.monthcount + " month" + (data.monthcount != 1 ? 's' : '')));
		if (data.benefactor)
			message.appendChild(document.createTextNode(", thanks to " + data.benefactor));
		message.appendChild(document.createTextNode("!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}

function twitch_subscription_mysterygift(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" has gifted " + data.subcount + " sub" + (data.subcount != 1 ? 's' : '') + " in the channel!"));
		message_container.appendChild(message);

		for (var i = 0; i < data.subscribers.length; i++) {
			var sub = data.subscribers[i];
			var sublist = createElementWithClass("div", "sublist" + (sub.avatar ? " with-avatar" : ""));

			if (sub.avatar) {
				var avatar = createElementWithClass("img", "avatar");
				avatar.src = sub.avatar;
				sublist.appendChild(avatar);
			}

			var sub_message = createElementWithClass("p", "message");
			var nickname = createElementWithClass("span", "nickname");
			nickname.appendChild(document.createTextNode(sub.name));
			sub_message.appendChild(nickname);
			if (sub.monthcount)
				sub_message.appendChild(document.createTextNode(" for " + sub.monthcount + " month" + (sub.monthcount != 1 ? 's' : '') + "!"));
			else
				sub_message.appendChild(document.createTextNode(" is a new subscriber!"));
			sublist.append(sub_message);

			message_container.appendChild(sublist);
		}
	});
}

function twitch_cheer(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user with-avatar");
		container.appendChild(user);

		var avatar = createElementWithClass("img", "avatar");
		avatar.src = "https://static-cdn.jtvnw.net/bits/light/static/" + data.level + "/3";
		user.appendChild(avatar);

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" has cheered with "));
		var bits = createElementWithClass("span", "cheer " + data.level);
		bits.appendChild(document.createTextNode(data.bits));
		message.appendChild(bits);
		message.appendChild(document.createTextNode(" bits!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}

function twitch_raid(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" just raided with " + data.count + " viewers!"));
		message_container.appendChild(message);
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

		if (data.patreon.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.patreon.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.twitch ? data.twitch.name : data.patreon.full_name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" is now supporting " + window.PATREON_CREATOR_NAME + " on Patreon!"));
		message_container.appendChild(message);
	});
}

function youtube_membership(data) {
	if (data.ismulti)
		return;
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" became a channel member"));
		if (data.benefactor)
			message.appendChild(document.createTextNode(", thanks to " + data.benefactor));
		message.appendChild(document.createTextNode("!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}

function youtube_membership_milestone(data) {
	if (data.ismulti)
		return;
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" has been a channel member for " + data.monthcount + " month" + (data.monthcount != 1 ? 's' : '')));
		if (data.benefactor)
			message.appendChild(document.createTextNode(", thanks to " + data.benefactor));
		message.appendChild(document.createTextNode("!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}

function youtube_membership_gift(data) {
	if (data.count == 1)
		return;
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" has gifted " + data.count + " membership" + (data.count != 1 ? 's' : '') + " in the channel!"));
		message_container.appendChild(message);

		for (var i = 0; i < data.members.length; i++) {
			var member = data.members[i];
			var sublist = createElementWithClass("div", "sublist" + (member.avatar ? " with-avatar" : ""));

			if (member.avatar) {
				var avatar = createElementWithClass("img", "avatar");
				avatar.src = member.avatar;
				sublist.appendChild(avatar);
			}

			var sub_message = createElementWithClass("p", "message");
			var nickname = createElementWithClass("span", "nickname");
			nickname.appendChild(document.createTextNode(member.name));
			sub_message.appendChild(nickname);
			if (member.monthcount)
				sub_message.appendChild(document.createTextNode(" for " + member.monthcount + " month" + (member.monthcount != 1 ? 's' : '') + "!"));
			else
				sub_message.appendChild(document.createTextNode(" is a new member!"));
			sublist.append(sub_message);

			message_container.appendChild(sublist);
		}
	});
}

function youtube_super_chat(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.avatar ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.avatar) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.avatar;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" has sent a Super Chat for "));
		var amount = createElementWithClass("span", "super-chat level-" + data.level);
		amount.appendChild(document.createTextNode(data.amount));
		message.appendChild(amount);
		message.appendChild(document.createTextNode("!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}

function youtube_super_sticker(data) {
	create_row(data, function (container) {
		var user = createElementWithClass("div", "user" + (data.sticker_url ? " with-avatar" : ""));
		container.appendChild(user);

		if (data.sticker_url) {
			var avatar = createElementWithClass("img", "avatar");
			avatar.src = data.sticker_url;
			avatar.alt = data.alt_text;
			avatar.title = data.alt_text;
			user.appendChild(avatar);
		}

		var message_container = createElementWithClass("div", "message-container");
		user.appendChild(message_container);

		var message = createElementWithClass("p", "system-message");
		var nickname = createElementWithClass("span", "nickname");
		nickname.appendChild(document.createTextNode(data.name));
		message.appendChild(nickname);
		message.appendChild(document.createTextNode(" has sent a Super Sticker for "));
		var amount = createElementWithClass("span", "super-chat level-" + data.level);
		amount.appendChild(document.createTextNode(data.amount));
		message.appendChild(amount);
		message.appendChild(document.createTextNode("!"));
		message_container.appendChild(message);

		if (data.message) {
			var user_message = createElementWithClass("p", "message");
			message_container.appendChild(user_message);
			var quote = document.createElement("q");
			if (data.messagehtml) {
				quote.innerHTML = data.messagehtml;
			} else {
				quote.appendChild(document.createTextNode(data.message));
			}
			user_message.appendChild(quote);
		}
	});
}
