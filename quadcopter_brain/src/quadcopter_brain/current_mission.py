#!/usr/bin/env python

import rospy

from quadcopter import Quadcopter
from quadcopter_brain import QuadcopterBrain
from rc_command import RCCommand
from waypoint_tools import WaypointTools


def print_position_data(quadcopter):
    rospy.loginfo("Position data:")
    rospy.loginfo("\tLatitude: %.8f" % quadcopter.current_lat)
    rospy.loginfo("\tLongitude: %.8f" % quadcopter.current_long)
    rospy.loginfo("\tRelative Altitude: %.2f" % quadcopter.current_rel_alt)
    rospy.loginfo("\tAltitude: %.2f" % quadcopter.current_alt)
    rospy.loginfo("\tHeading: %.2f" % quadcopter.heading)


def main():
    carl = QuadcopterBrain()

    # Quadcopter node (carl) must be initialized before get_param will work
    outside = rospy.get_param("Quadcopter/outside", False)
    rospy.loginfo("In outside mode: %s.", outside)
    rospy.loginfo("If incorrect, add _outside:=True to the rosrun call")

    carl.quadcopter.clear_waypoints()
    rospy.loginfo("Sleeping for 3 seconds...")
    rospy.sleep(3)

    # great_lawn_waypoints = WaypointTools.open_waypoint_file(
    #     "great_lawn_waypoints.json")

    if outside:
        carl.arm()
    carl.launch()
    #carl.rc_square_dance()

    carl.rc_land_on_fiducial()
    carl.quadcopter.return_rc_control()
    # carl.go_to_waypoints([great_lawn_waypoints['A'],
    #                       great_lawn_waypoints['B5'],
    #                       great_lawn_waypoints['C10']])
    # carl.land()


if __name__ == '__main__':
    main()
