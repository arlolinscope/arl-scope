#!/usr/bin/env python

import time
import json
import math
import os

import rospkg
import rospy
import rosbag
import roscopter
import roscopter.msg
import roscopter.srv
from std_srvs.srv import *
from sensor_msgs.msg import NavSatFix, NavSatStatus, Imu
from geodesy import utm

from flight_error import FlightError
from position_tools import PositionTools


class QuadcopterBrain(object):
    '''
    High-level quadcopter controller.
    '''
    def __init__(self):
        self.clear_waypoints_service = rospy.ServiceProxy(
            'clear_waypoints', Empty)
        self.command_service = rospy.ServiceProxy(
            'command', roscopter.srv.APMCommand)
        self.waypoint_service = rospy.ServiceProxy(
            'waypoint', roscopter.srv.SendWaypoint)
        self.trigger_auto_service = rospy.ServiceProxy(
            'trigger_auto', Empty)
        self.adjust_throttle_service = rospy.ServiceProxy(
            'adjust_throttle', Empty)
        self.current_lat = 0.0
        self.current_long = 0.0
        self.current_rel_alt = 0.0
        self.current_alt = 0.0
        self.heading = 0.0
        rospy.Subscriber("/filtered_pos", roscopter.msg.FilteredPosition,
                         self.position_callback)

    def arm(self):
        self.command_service(roscopter.srv.APMCommandRequest.CMD_ARM)
        print('Armed')

    def launch(self):
        self.command_service(roscopter.srv.APMCommandRequest.CMD_LAUNCH)
        print('Launched')
        time.sleep(5)

    def go_to_waypoints(self, waypoint_data):
        waypoints = [build_waypoint(datum) for datum in waypoint_data]
        for waypoint in waypoints:
            self.send_waypoint(waypoint)

    def land(self):
        self.command_service(roscopter.srv.APMCommandRequest.CMD_LAND)
        print('Landing')

    def hover_in_place(self):
        lat = mavlink_to_gps(self.current_lat)
        lon = mavlink_to_gps(self.current_long)
        alt = mavlink_to_gps(self.current_rel_alt)
        self.go_to_waypoints([{"latitude": lat,
                               "longitude": lon,
                               "altitude": alt}])

    def send_waypoint(self, waypoint):
        self.trigger_auto_service()
        self.adjust_throttle_service()
        successfully_sent_waypoint = False
        tries = 0
        while not successfully_sent_waypoint and tries < 5:
            res = self.waypoint_service(waypoint)
            successfully_sent_waypoint = res.result
            tries += 1
            if successfully_sent_waypoint:
                print('Sent waypoint %d, %d' % (waypoint.latitude,
                                                waypoint.longitude))
                print self.check_reached_waypoint(waypoint, max_wait_time=15)
            else:
                print("Failed to send waypoint %d, %d" % (waypoint.latitude,
                                                          waypoint.longitude))
                time.sleep(0.1)
                if tries == 5:
                    print("Tried %d times and giving up" % (tries))
                else:
                    print("Retrying. Tries: %d" % (tries))

    def check_reached_waypoint(self, waypoint, max_wait_time=50, wait_time=0):
        rospy.Subscriber("/filtered_pos", roscopter.msg.FilteredPosition,
                         self.position_callback)
        while (not self.has_reached_waypoint(waypoint)) and \
            wait_time < max_wait_time:
            time.sleep(5)
            wait_time += 5
            print "--> Traveling to waypoint for %d seconds" % (wait_time)
            print "--> Current position is %d, %d" % (self.current_lat,
                                                      self.current_long)
        if wait_time < max_wait_time:  # successfully reached
            time.sleep(5)  # stay at waypoint for a few seconds
            return "Reached waypoint"
        else:
            return self.waypoint_timeout_choice(waypoint, wait_time)

    def waypoint_timeout_choice(self, waypoint, curr_wait_time):
        print "TIMEOUT: Traveling to waypoint for %d sec." % (curr_wait_time)
        opt1 = "\t 1 - Continue traveling to waypoint\n" 
        opt2 = "\t 2 - Continue to next command \n"
        opt3 = "\t 3 - Terminate \n"
        options = "\t Choose an option number:\n%s%s%s>>> " % (opt1,opt2,opt3)
        msg = options
        while True:  # I'm sorry.
            rospy.sleep(0.1)  # there's some weird not getting input thing
            try:
                choice = raw_input(msg)
                if choice == '1':
                    print "Continuing toward waypoint."
                    return self.check_reached_waypoint(waypoint,
                        max_wait_time=curr_wait_time*2, wait_time=curr_wait_time)
                elif choice == '2':
                    return "Failed to reach waypoint. " \
                            "Continuing to next command"
                elif choice == '3':
                    raise FlightError("Timeout going to waypoint", self)
                else:
                    raise SyntaxError  # this gets caught in the except
            except (SyntaxError, EOFError, NameError):
                print "Invalid Choice."
                msg = "Enter either 1, 2, or 3. \n>>> "

    def has_reached_waypoint(self, waypoint, xy_error_margin=3,
                             alt_error_margin=1):
        """ Waypoint is roscopter waypoint type
            error margins are in meters

            returns boolean of whether position is within error margins"""
        try:
            _, _, dist = PositionTools.lon_lon_diff(self.current_lat,
                                                    self.current_lon,
                                                    waypoint.latitude,
                                                    waypoint.longitude)
            alt_diff = math.fabs(self.current_alt - waypoint.altitude)
            return dist < xy_error_margin and alt_diff < alt_error_margin
        except AttributeError:  # if haven't gotten current position data
            return False

    def position_callback(self, data):
        self.current_lat = mavlink_to_gps(data.latitude)
        self.current_long = mavlink_to_gps(data.longitude)
        self.current_rel_alt = data.relative_altitude / 1000.0  # From mm to m
        self.current_alt = data.altitude / 1000.0  # From mm to m
        self.heading = data.heading

    def fly_path(self, waypoint_data):
        self.launch()
        self.go_to_waypoints(waypoint_data)
        # self.land()


def build_waypoint(data):
    '''
    data: dictionary with latitude and longitude
          (altitude and hold_time optional)
    '''
    latitude = data['latitude']
    longitude = data['longitude']
    altitude = data.get('altitude', 8)
    hold_time = data.get('hold_time', 3.0)

    waypoint = roscopter.msg.Waypoint()
    waypoint.latitude = gps_to_mavlink(latitude)
    waypoint.longitude = gps_to_mavlink(longitude)
    waypoint.altitude = int(altitude * 1000)
    waypoint.hold_time = int(hold_time * 1000)  # in ms
    waypoint.waypoint_type = roscopter.msg.Waypoint.TYPE_NAV
    return waypoint


def gps_to_mavlink(coordinate):
    '''
    coordinate: decimal degrees
    '''
    return int(coordinate * 1e7)

def mavlink_to_gps(coordinate):
    '''
    coordinate: integer representation of degrees
    '''
    return coordinate / 1e7


def open_waypoint_file(filename):
    rospack = rospkg.RosPack()
    quadcopter_brain_path = rospack.get_path("quadcopter_brain")
    source_path = "src"
    file_path = os.path.join(quadcopter_brain_path, source_path, filename)
    with open(file_path, "r") as f:
        waypoints = json.load(f)
    return waypoints


def main():
    rospy.init_node("quadcopter_brain")
    # In order to set the outside parameter, add _outside:=True to rosrun call
    outside = rospy.get_param("quadcopter_brain/outside", False)
    print "Outside = ", outside
    carl = QuadcopterBrain()
    carl.clear_waypoints_service()
    print "Sleeping for 3 seconds to prepare system..."
    rospy.sleep(3)
    great_lawn_waypoints = open_waypoint_file(
        "waypoint_data/great_lawn_waypoints.json")
    if outside:
        carl.arm()
    carl.fly_path([great_lawn_waypoints["G"], great_lawn_waypoints["D"]])


if __name__ == '__main__':
    main()
