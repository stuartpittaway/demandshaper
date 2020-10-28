import requests
import argparse
import json
import time
from datetime import datetime, date, time, timedelta
import os.path
from os import path
import time, random
import logging
from socket import *
from enum import Enum


# Inspired by https://tesla-api.timdorr.com/api-basics/authentication

class TeslaAPI:
    api_url="https://owner-api.teslamotors.com/api/1"
    api_oauth_url="https://owner-api.teslamotors.com/oauth/token"
    ownerapi_client_id="81527cff06843c8634fdc09e8ac0abefb46ac849f38fe1e431c2ef2106796384"
    ownerapi_client_secret="c7257eb71a564034f9419ee651c7d0e5f7aa6bfbd18bafb5c5c033b093bb2fa3"
    tesla_token=None
    tesla_token_expiry=None

    def __init__(self,):
        pass

    def getTokenFromUsernamePassword(self, email, password):
        oauth_param = {
                "grant_type": "password",
                "client_id": self.ownerapi_client_id,
                "client_secret": self.ownerapi_client_secret,
                "email": email,
                "password": password,
            }

        self.setToken(self.request_oauth(oauth_param))
        return True

    def setToken(self, token):
        self.tesla_token = token
        self.updateTokenExpiry()
        logging.info("API Token Updated, expires "+str(self.tesla_token_expiry))
        self.checkTokenExpiry()

    def updateTokenExpiry(self):
        self.tesla_token_expiry = datetime.fromtimestamp(self.tesla_token['created_at']+self.tesla_token['expires_in'])

    def request_oauth(self, params):
        try:
            r = requests.post(self.api_oauth_url, data=params)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            raise SystemExit(e)

    def httpget(self, *args, **kwargs):
        logging.debug(*args)
        return(requests.get(*args, **kwargs))

    def httppost(self, *args, **kwargs):
        logging.debug(*args)
        return(requests.post(*args, **kwargs))

    def renew_access_token(self):
        oauth_param = {
                    "grant_type": "refresh_token",
                    "client_id": self.ownerapi_client_id,
                    "client_secret": self.ownerapi_client_secret,
                    "refresh_token": self.tesla_token['refresh_token'],
                }

        self.setToken(self.request_oauth(oauth_param))
        return True

    def checkTokenExpiry(self):
        if self.tesla_token==None:
            raise Exception("API token not available")

        # If the token is due to expire within 3 days of today, renew it
        if self.tesla_token_expiry < (datetime.utcnow() + timedelta(days=3)):
            self.renew_access_token()

    def api_get(self, endpointurl):
        self.checkTokenExpiry()
        return self.httpget(endpointurl, headers=self.headers())

    def api_post(self, endpointurl, data):
        self.checkTokenExpiry()
        return self.httppost(endpointurl, data=data, headers=self.headers())

    def headers(self):
        return {"Authorization": "{} {}".format(self.tesla_token['token_type'], self.tesla_token['access_token'])}

    def vehicles(self):
        return self.api_get(self.api_url + "/vehicles").json()

    def charge_state(self, id):
        return self.api_get(self.api_url + '/vehicles/{id}/data_request/charge_state'.format(id=id)).json()

    def vehicle_data(self, id):
        return self.api_get(self.api_url + '/vehicles/{id}/vehicle_data'.format(id=id)).json()

    def vehicle_data_legacy(self, id):
        return self.api_get(self.api_url + '/vehicles/{id}/data'.format(id=id)).json()

    def startcharging(self,id):
        logging.info("Starting charge")
        reply=self.api_post(self.api_url + "/vehicles/{id}/command/charge_start".format(id=id), data='').json()
        if reply['response']==None:
            return None
        return reply['response']['result']

    def stopcharging(self,id):
        logging.info("Stop charge")
        reply=self.api_post(self.api_url + "/vehicles/{id}/command/charge_stop".format(id=id), data='').json()
        return reply['response']['result']


    def wakeup(self, id):
        logging.info("Waking up car...")
        #Loop 12 times (60 second timeout)
        timeout=12
        while timeout>0:
            reply=self.api_post(self.api_url + "/vehicles/{id}/wake_up".format(id=id), data='').json()
            if reply['response']['id']==id and reply['response']['state']=='online':
                return True
            #wait for 5 seconds
            time.sleep(5)
            timeout-=1

        logging.error("Could not wake car")
        return False



