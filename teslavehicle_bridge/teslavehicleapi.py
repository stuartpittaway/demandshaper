import requests
from TeslaAPI import TeslaAPI
import argparse
import json
import time
from datetime import datetime, date, time, timedelta
import os.path
from os import path
import time, random
import paho.mqtt.client as mqtt
import logging
from socket import *
from enum import Enum


class RequestChargeState(Enum):
    IDLE=1
    STOPCHARGE=2
    STARTCHARGE=3




# Main program code
parser = argparse.ArgumentParser(
    description='Tesla API to MQTT interface',
    epilog="Written for the Open Energy Monitor project https://openenergymonitor.org/",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--username', help='Tesla account Username')
parser.add_argument('--password', help='Tesla account Password')
parser.add_argument('--name', help='Vehicle name (display name) to filter on (if more than 1 vehicle on account)')
parser.add_argument('--cache', help='Filename of cache file to hold Tesla token/credentials',default='tesla_token.json')
parser.add_argument('--mqttcredfile', help='Filename of JSON file which holds MQTT credentials',default='mqtt_creds.json')
parser.add_argument('--interval', help='How many minutes between API poll to see if vehicle is awake',default=15)
parser.add_argument('--charginginterval', help='How many minutes between API poll when vehicle is charging',default=1)
parser.add_argument('--wakeinterval', help='Wake up vehicle interval (minutes)',default=720)
parser.add_argument('--loglevel', help='Set logging level',default='DEBUG')
args = parser.parse_args()


numeric_level = getattr(logging, args.loglevel.upper(), None)
if not isinstance(numeric_level, int):
    raise ValueError('Invalid log level: %s' % loglevel)
logging.basicConfig(level=numeric_level)

logging.debug(args)

# Nasty global variables....
global id
global requestchargestate
global vehicle_charging
global vehicle_chargeportlocked
global api
global v
global timer_setting

timer_setting="00 00 00 00"

v=None
requestchargestate=RequestChargeState.IDLE
vehicle_charging=False
vehicle_chargeportlocked=False

api=TeslaAPI()

# Are we going to use the cached credentials?
if args.password==None and args.username==None:
    if path.exists(args.cache):
        with open(args.cache) as json_file:
            api.setToken(json.load(json_file))
    else:
        raise Exception("Token cache file not found")
else:
    if args.username==None:
        raise Exception("Username not supplied")

    if args.password==None:
        raise Exception("Password not supplied")

    api.getTokenFromUsernamePassword(args.username,args.password)

    logging.info('Saving token to '+args.cache+'. For security, you should now run the program without the username and password parameters')
    with open(args.cache, 'w') as outfile:
        json.dump(api.tesla_token, outfile)

    exit()


# Get a list of all the vehicles on the account
vehicles=api.vehicles()

if vehicles['count']==0:
    raise Exception("No vehicles on account")

if vehicles['count']>1 and args.name==None:
    raise Exception("More than 1 vehicle on account but name argument not specified")

if args.name!=None:
    # Find vehicle here
    for vehicle in vehicles['response']:
        if vehicle['display_name']==args.name:
            v=vehicle
else:
    #Pick the first vehicle in the results (there is only 1)
    v=vehicles['response'][0]

if v==None:
    raise Exception("Cannot find vehicle")

# Global variable holds identifier of vehicle
id=v['id']

# -------------------------------------------------------------------------------------
# Connect to EmonPi MQTT server
# -------------------------------------------------------------------------------------
def emonpi_on_connect(client, userdata, flags, rc):
    logging.info("Connected with result code "+str(rc))
    client.subscribe(mqttcred["basetopic"]+"/teslavehicle/rapi/in/#")

def emonpi_on_message(client, userdata, msg):
    global requestchargestate
    global timer_setting

    logging.debug("Message "+str(msg.topic)+"  ["+str(msg.payload.decode())+"]")

    if msg.topic.endswith("/rapi/in/timerstate"):
        mqtt_emonpi.publish(mqttcred["basetopic"]+"/teslavehicle/rapi/out/timerstate",timer_setting,0)

    if msg.topic.endswith("/rapi/in/state"):
        #Default to off
        state="0 254"
        if vehicle_charging==True:
            state="0 1"

        mqtt_emonpi.publish(mqttcred["basetopic"]+"/teslavehicle/rapi/out/state",state,0)

    if msg.topic.endswith("/rapi/in/settimer"):
        timer_setting=str(msg.payload.decode())
 
    if msg.topic.endswith("/rapi/in/charge"):
        if str(msg.payload.decode())=="1":
            # Start charging
            requestchargestate=RequestChargeState.STARTCHARGE
        else:
            # Stop charging
            requestchargestate=RequestChargeState.STOPCHARGE


def emonpi_on_disconnect(client, userdata,rc=0):
#    logging.debug("Disconnected result code "+str(rc))
    mqtt_emonpi.loop_stop()

#def emonpi_on_subscribe(client, userdata, mid, granted_qos):
#    logging.debug("emonpi_on_subscribe")

def GetVehicleChargeState():
    global vehicle_charging
    global vehicle_chargeportlocked
    logging.debug("GetVehicleChargeState")

    attributes = ['battery_level',
    'battery_range',
    'charge_current_request',
    'charge_current_request_max',
#    'charge_enable_request',
#    'charge_energy_added',
    'charge_limit_soc',
    'charge_limit_soc_min',
    'charge_limit_soc_max',
    'charge_port_latch',
    'charge_rate',
    'charger_actual_current',
    'charging_state',
    'charger_voltage',
    'charger_power',
    'minutes_to_full_charge',
#    'scheduled_charging_pending',
#    'scheduled_charging_start_time',
#    'time_to_full_charge'
     ]
    # v is a global variable

    # Discover the charge and battery state
    chargestate=api.charge_state(id)

    if chargestate['response']==None:
        logging.error("No response to charge state request")
        return

    for val in attributes:
        value=chargestate['response'][val]

        if val=='charge_port_latch':
            vehicle_chargeportlocked=True if value=='Engaged' else False
            value= 1 if value=='Engaged' else 0

        if val=='charging_state':
            vehicle_charging=True if value=='Charging' else False
            value=1 if value=='Charging' else 0

        logging.debug("MQTT:"+val+"="+str(value))
        # Publish to MQTT
        mqtt_emonpi.publish(mqttcred["basetopic"]+"/teslavehicle/"+val,value,0)



global mqttcred
# Get the MQTT credentials from file
mqttcred = {"hostname": "emonpi.local", "port": 1883, "username": None, "password": None, "basetopic": None}

if path.exists(args.mqttcredfile):
    with open(args.mqttcredfile) as json_file:
        mqttcred=(json.load(json_file))
else:
    # Wait for UDP packet to be seen on the network from emoncms Demand Shaper
    sock=socket(AF_INET, SOCK_DGRAM)
    sock.settimeout(20)
    sock.bind(('',5005))

    while (1):
        try:
            m=sock.recvfrom(256)
            break
        except timeout:
            logging.warning('Timeout waiting for UDP packet from emonCMS Demand Shaper')

    url="http://"+str(m[1][0])+"/emoncms/device/auth/request.json"

    #Wait maximum 60 seconds
    counter=60
    while (counter>0):
        logging.info("Requesting authentication from emonCMS")
        reply=requests.get(url,None)
        if reply.text.startswith("Authentication request registered"):
            time.sleep(2)
            counter+-1
        else:
            break

    if counter==0:
        raise Exception("Timed out waiting for user to accept")

    parts=reply.text.split(':',4)
    mqttcred["hostname"]=m[1][0]
    mqttcred["port"]=1883
    mqttcred["username"]=parts[0]
    mqttcred["password"]=parts[1]
    mqttcred["basetopic"]=parts[2]

    logging.info('Saving MQTT creds to '+args.mqttcredfile+'. For security, you ensure the relevant permissions are set on this file')
    with open(args.mqttcredfile, 'w') as outfile:
        json.dump(mqttcred, outfile)

mqtt_emonpi = mqtt.Client("tesla_api_"+str(time.time())[6:-3])
mqtt_emonpi.on_connect = emonpi_on_connect
mqtt_emonpi.on_message = emonpi_on_message
mqtt_emonpi.on_disconnect = emonpi_on_disconnect

# Connect to Emoncms Local MQTT Server
try:
    mqtt_emonpi.username_pw_set(mqttcred["username"], mqttcred["password"])
    mqtt_emonpi.connect(mqttcred["hostname"], port=mqttcred["port"], keepalive=30)
    mqtt_emonpi.loop_start()
except Exception:
    raise Exception ("Could not connect to emonPi MQTT server")



sleepseconds=5
# args.wakeinterval is in minutes
wakecountdown=args.wakeinterval*60/sleepseconds
countdown=1

# Loop
while 1:
    #logging.debug("Loop:"+str(countdown)+", "+str(wakecountdown)+", Charging: "+str(vehicle_charging)+", Port locked:"+str(vehicle_chargeportlocked)+", State="+str(requestchargestate))

    #Sleep for 5 seconds
    time.sleep(sleepseconds)

    wakecountdown=wakecountdown-1
    countdown=countdown-1

    if wakecountdown==0:
        api.wakeup(id)
        wakecountdown=args.wakeinterval*60/sleepseconds
        #Force a reading to be taken
        countdown=0

    if countdown==0:
        logging.debug('Countdown zero, checking vehicle state')
        legacy=api.vehicle_data_legacy(id)

        if legacy['response']!=None:
            logging.info("Vehicle state "+legacy['response']['state'])
            #If vehicle is awake, then take a reading otherwise let it sleep
            if legacy['response']['id']==id and legacy['response']['state']=='online':
                GetVehicleChargeState()
                mqtt_emonpi.publish(mqttcred["basetopic"]+"/teslavehicle/sleep",2,0)
        else:
            #  'error': 'vehicle unavailable:
            logging.debug(legacy['error'])
            # Record when we find the car asleep for audit purposes
            mqtt_emonpi.publish(mqttcred["basetopic"]+"/teslavehicle/sleep",1,0)

        if vehicle_charging:
            countdown=args.charginginterval*60/sleepseconds
        else:
            #Reset timer to 15 minutes
            countdown=args.interval*60/sleepseconds


    if requestchargestate==RequestChargeState.STARTCHARGE:
        requestchargestate=RequestChargeState.IDLE
        if vehicle_charging==False:
            api.wakeup(id)
            # Update the charge state
            GetVehicleChargeState()
            if vehicle_charging==False and vehicle_chargeportlocked:
                # Now start the charge
                if api.startcharging(id)==None:
                    logging.warning("Failed to start charge")
                # Make sure we query the car very soon in the loop
                countdown=2

    if requestchargestate==RequestChargeState.STOPCHARGE:
        requestchargestate=RequestChargeState.IDLE
        if vehicle_charging:
            api.wakeup(id)
            #Update the charge state
            GetVehicleChargeState()
            if vehicle_charging==True:
                # Stop the charge
                api.stopcharging(id)
                # Make sure we query the car very soon in the loop
                countdown=2
