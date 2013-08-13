# -*- coding: utf-8 -*-
from flask import Flask, request, json, render_template, redirect, url_for, \
    flash
from flask.ext.sqlalchemy import SQLAlchemy
from twilio.rest import TwilioRestClient
from requests import get as rget
from datetime import datetime as dt
from sns import is_message_signature_valid
import local_settings

app = Flask(__name__)
app.secret_key = local_settings.FLASK_SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tmp/test.db'
db = SQLAlchemy(app)
twilio_client = TwilioRestClient(local_settings.ACCOUNT_SID,
                                 local_settings.AUTH_TOKEN)


class Snstopic(db.Model):
    arn = db.Column(db.String(60), primary_key=True)
    status = db.Column(db.Integer)
    confirmation_url = db.Column(db.String(600))

    def __init__(self, arn, confirmation_url):
        self.arn = arn
        self.status = 0
        self.confirmation_url = confirmation_url

    def __repr__(self):
        return '<Arn %r>' % self.arn


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120))
    telephone = db.Column(db.String(20))
    snstopic_arn = db.Column(db.String(60), db.ForeignKey('snstopic.arn'))
    snstopic = db.relationship('Snstopic', backref=db.backref('users',
                                                              lazy='dynamic'))

    def __init__(self, email, telephone, snstopic):
        self.email = email
        self.telephone = telephone
        self.snstopic = snstopic

    def __repr__(self):
        return '<User %r>' % self.email


class Notification(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    timestamp = db.Column(db.DateTime())
    subject = db.Column(db.String(160))
    message = db.Column(db.String())
    snstopic_arn = db.Column(db.String(60), db.ForeignKey('snstopic.arn'))
    snstopic = db.relationship('Snstopic', backref=db.backref('notifications',
                                                              lazy='dynamic'))

    def __init__(self, id, timestamp, subject, message, snstopic):
        self.id = id
        self.timestamp = timestamp
        self.subject = subject
        self.message = message
        self.snstopic = snstopic

    def __repr__(self):
        return '<Notification %r>' % self.id


@app.route('/')
def topics():
    return render_template('index.html', topics=Snstopic.query.all())


@app.route('/topic/<string:topic_arn>', methods=['GET', 'POST'])
def show_topic(topic_arn):
    topic = Snstopic.query.get(topic_arn)
    if request.method == 'POST':
        user = User(request.form.get('email'), request.form.get('telephone'),
                    topic)
        db.session.add(user)
        db.session.commit()
        flash(u'User added!', 'success')
    return render_template('topic.html', topic=topic)


@app.route('/topic/<string:topic_arn>/confirm', methods=['GET'])
def confirm_topic(topic_arn):
    topic = Snstopic.query.get(topic_arn)
    if topic.status == 0:
        r = rget(topic.confirmation_url)
        if r.status_code == 200:
            topic.status = 1
            db.session.commit()
            flash(u'Subscription confirmed!', 'success')
        else:
            flash(u'Subscription not confirmed! Response code was %i' %
                  r.status_code, 'danger')
    else:
        flash(u'Subscription already confirmed!', 'danger')
    return redirect(url_for('show_topic', topic_arn=topic.arn))


@app.route('/%s' % local_settings.SNS_ENDPOINT, methods=['POST'])
def sns():
    headers = request.headers
    arn = headers.get('x-amz-sns-topic-arn')
    obj = json.loads(request.data)
    assert is_message_signature_valid(obj)
    if headers.get('x-amz-sns-message-type') == 'SubscriptionConfirmation':
        confirmation_url = obj[u'SubscribeURL']
        topic = Snstopic(arn, confirmation_url)
        db.session.add(topic)
        db.session.commit()
    elif headers.get('x-amz-sns-message-type') == 'Notification':
        topic = Snstopic.query.get(arn)
        notification_id = obj[u'MessageId']
        timestamp = dt.strptime(obj[u'Timestamp'], '%Y-%m-%dT%H:%M:%S.%fZ')
        message = obj[u'Message']

        msg_subject = obj[u'Subject'] if u'Subject' in obj.keys() else 'empty'
        subject = local_settings.PRE_SUBJECT + msg_subject

        notification = Notification(notification_id, timestamp, subject,
                                    message, topic)
        db.session.add(notification)
        db.session.commit()

        for user in topic.users:
            create_sms = twilio_client.sms.messages.create
            message = creae_sms(to=user.telephone,
                                from_=local_settings.FROM_NUMBER, body=subject)
    return '', 200

if __name__ == '__main__':
    app.debug = True
    app.run()
