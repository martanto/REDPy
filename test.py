import redpy
import argparse

parser = argparse.ArgumentParser(description=
    "Backfills table with data from the past")
parser.add_argument("-v", "--verbose", action="count", default=0,
    help="increase written print statements")
parser.add_argument("-t", "--troubleshoot", action="count", default=0,
    help="run in troubleshoot mode (without try/except)")
parser.add_argument("-s", "--starttime",
    help="optional start time to begin filling (YYYY-MM-DDTHH:MM:SS)")
parser.add_argument("-e", "--endtime",
    help="optional end time to end filling (YYYY-MM-DDTHH:MM:SS)")
parser.add_argument("-c", "--configfile",
    help="use configuration file named CONFIGFILE instead of default settings.cfg")
parser.add_argument("-n", "--nsec", type=int,
    help="overwrite opt.nsec from configuration file with NSEC this run only")
args = parser.parse_args()


opt = redpy.config.Options(args.configfile)

h5file, rtable, otable, ttable, ctable, jtable, dtable, ftable = redpy.table.openTable(opt)

redpy.plotting.createPlots(rtable, ftable, ttable, ctable, otable, opt)