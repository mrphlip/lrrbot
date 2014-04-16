#!/usr/bin/env python3
import server
import index
import notifications
import stats
import login
import archive
import votes
import botinteract
import secrets

server.app.secret_key = secrets.session_secret

app = server.app
__all__ = ['app']
