<?php
class teslavehicle
{
    private $mqtt_client = false;
    private $basetopic = "";
    private $last_ctrlmode = array();
    private $last_timer = array();
    private $last_soc_update = 0;

    public function __construct($mqtt_client,$basetopic) {
        $this->mqtt_client = $mqtt_client;
        $this->basetopic = $basetopic;
    }

    public function default_settings() {
        $defaults = new stdClass();
        $defaults->soc_source = "input"; // time, energy, distance, input, ovms
        $defaults->battery_capacity = 55.0;
        $defaults->charge_rate = 7.2;
        $defaults->target_soc = 0.8;
        $defaults->current_soc = 0.2;
        $defaults->balpercentage = 1.0;
        $defaults->baltime = 2.0;
        $defaults->car_economy = 4.0;
        $defaults->charge_energy = 0.0;
        $defaults->charge_distance = 0.0;
        $defaults->distance_units = "miles";
        $defaults->ovms_vehicleid = "";
        $defaults->ovms_carpass = "";
        $defaults->divert_mode = 0;
        return $defaults;
    }

    public function set_basetopic($basetopic) {
        schedule_log("TESLA: $device base topic set to $basetopic");
        $this->basetopic = $basetopic;
    }

    public function get_time_offset() {
        return 0;
    }

    public function on($device) {
        $device = $this->basetopic."/$device";
        if (!isset($this->last_ctrlmode[$device])) $this->last_ctrlmode[$device] = "";
        $this->last_timer[$device] = "00 00 00 00";
        if ($this->last_ctrlmode[$device]!="on") {
            $this->last_ctrlmode[$device] = "on";
            $this->mqtt_client->publish("$device/rapi/in/charge","1",0);
            schedule_log("TESLA: $device switch on");
        }
    }

    public function off($device) {
        $device = $this->basetopic."/$device";
        if (!isset($this->last_ctrlmode[$device])) $this->last_ctrlmode[$device] = "";
        $this->last_timer[$device] = "00 00 00 00";
        if ($this->last_ctrlmode[$device]!="off") {
            $this->last_ctrlmode[$device] = "off";
            $this->mqtt_client->publish("$device/rapi/in/charge","0",0);
            schedule_log("TESLA: $device switch off");
        }
    }

    public function timer($device,$s1,$e1,$s2,$e2) {
        $device = $this->basetopic."/$device";
        $this->last_ctrlmode[$device] = "timer";

        $timer_str = time_conv_dec_str($s1," ")." ".time_conv_dec_str($e1," ");
        if (!isset($this->last_timer[$device])) $this->last_timer[$device] = "";

        if ($timer_str!=$this->last_timer[$device]) {
            $this->last_timer[$device] = $timer_str;
            $this->mqtt_client->publish("$device/rapi/in/settimer",$timer_str,0);
            schedule_log("TESLA: $device set timer $timer_str");
        }
    }

    public function set_divert_mode($device,$mode) {
        $device = $this->basetopic."/$device";
        $mode = (int) $mode;
        $mode += 1;
        if (!isset($this->last_divert_mode[$device])) $this->last_divert_mode[$device] = "";
        if ($this->last_divert_mode[$device]!=$mode) {
            $this->last_divert_mode[$device] = $mode;
            $this->mqtt_client->publish("$device/rapi/in/divertmode",$mode,0);
            schedule_log("TESLA: $device divert mode $mode");
        }
    }

    public function send_state_request($device) {
        $this->mqtt_client->publish($this->basetopic."/$device/rapi/in/state","",0);
    }

    public function handle_state_response($schedule,$message,$timezone) {
        return false;
    }

    public function get_state($mqtt_request,$device,$timezone) {
        $valid = true;
        $state = new stdClass;

        // Get TESLA timer state
        if ($result = $mqtt_request->request($this->basetopic."/$device/rapi/in/timerstate","",$this->basetopic."/$device/rapi/out/timerstate")) {
            $ret = explode(" ",$result);
            if (count($ret)==4) {
                $state->timer_start1 = ((int)$ret[0])+((int)$ret[1]/60);
                $state->timer_stop1 = ((int)$ret[2])+((int)$ret[3]/60);
                $state->timer_start2 = 0;
                $state->timer_stop2 = 0;
            } else {
                $valid = false;
            }
        } else {
            $valid = false;
        }

        // Get TESLA API state
        if ($result = $mqtt_request->request($this->basetopic."/$device/rapi/in/state","",$this->basetopic."/$device/rapi/out/state")) {
            $ret = explode(" ",$result);
            if ($ret[1]==254) {
                if ($state->timer_start1==0 && $state->timer_stop1==0) {
                    $state->ctrl_mode = "off";
                } else {
                    $state->ctrl_mode = "timer";
                }
            }
            else if ($ret[1]==1 || $ret[1]==3) {
                if ($state->timer_start1==0 && $state->timer_stop1==0) {
                    $state->ctrl_mode = "on";
                } else {
                    $state->ctrl_mode = "timer";
                }
            }
        } else {
            $valid = false;
        }

        if ($valid) return $state; else return false;
    }

    public function auto_update_timeleft($schedule) {

        if ((time()-$this->last_soc_update)>600 && $schedule->settings->soc_source!='time') {
            $this->last_soc_update = time();

            if ($schedule->settings->soc_source=='input') {
                global $input;
                if ($feedid = $input->exists_nodeid_name($userid,$device,"soc")) {
                    $schedule->settings->current_soc = $input->get_last_value($feedid)*0.01;
                    schedule_log("Recalculating TESLA schedule based on emoncms input: ".$schedule->settings->current_soc);
                }
            }
            $kwh_required = ($schedule->settings->target_soc-$schedule->settings->current_soc)*$schedule->settings->battery_capacity;
            $schedule->settings->period = $kwh_required/$schedule->settings->charge_rate;

            if (isset($schedule->settings->balpercentage) && $schedule->settings->balpercentage < $schedule->settings->target_soc) {
                $schedule->settings->period += $schedule->settings->baltime;
            }
            $schedule->runtime->timeleft = $schedule->settings->period * 3600;
            schedule_log("TESLA timeleft: ".$schedule->runtime->timeleft);
        }
        return $schedule;
    }
}
