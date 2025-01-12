# REDPy - Repeating Earthquake Detector in Python
# Copyright (C) 2016-2020  Alicia Hotovec-Ellis (ahotovec-ellis@usgs.gov)
# Licensed under GNU GPLv3 (see LICENSE.txt)

from tables import *
import numpy as np
import matplotlib
import datetime
from datetime import timedelta
import matplotlib.pyplot as plt
import matplotlib.dates
import time
import pandas as pd
import redpy.cluster
import redpy.correlation
from redpy.printing import *
from redpy.optics import *
import os
import shutil
import glob
import urllib
import urllib.request
from obspy import UTCDateTime
from obspy.geodetics import locations2degrees
from obspy.taup import TauPyModel
import cartopy.crs as ccrs
import cartopy.io.img_tiles as cimgt
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from matplotlib.transforms import offset_copy
from bokeh.plotting import figure, output_file, save, gridplot
from bokeh.models import HoverTool, ColumnDataSource, OpenURL, TapTool, Range1d, Div, Span
from bokeh.models import Arrow, VeeHead, ColorBar, LogColorMapper, LinearColorMapper
from bokeh.models import *
from bokeh.models.glyphs import Line, Quad
from bokeh.models.formatters import LogTickFormatter
from bokeh.layouts import column
from bokeh.palettes import inferno, all_palettes
matplotlib.use('Agg')

# Adjust rcParams
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
matplotlib.rcParams['font.size'] = 8.0
matplotlib.rcParams['pdf.fonttype'] = 42


def createPlots(rtable, ftable, ttable, ctable, otable, opt):

    """
    Creates all output plots (core images, family plots, and two bokeh .html plots)

    rtable: Repeater table
    ftable: Families table
    ttable: Triggers table
    ctable: Correlation table
    otable: Orphan table
    opt: Options object describing station/run parameters

    """

    printTriggerCatalog(ttable, opt)
    printOrphanCatalog(otable, opt)
    if len(rtable)>1:
        plotTimelines(rtable, ftable, ttable, opt)
        if np.sum(ftable.cols.printme[:]):
            if opt.printVerboseCat == True:
                printVerboseCatalog(rtable, ftable, ctable, opt)
            else:
                printCatalog(rtable, ftable, opt)
            printSwarmCatalog(rtable, ftable, ttable, opt)
            printCoresCatalog(rtable, ftable, opt)
            # Need to make this optional. Too slow for very long datasets!
            #printEventsperDay(rtable, ftable, opt)
            plotCores(rtable, ftable, opt)
            plotFamilies(rtable, ftable, ctable, opt)
            plotFamilyHTML(rtable, ftable, opt)
            ftable.cols.printme[:] = np.zeros((len(ftable),))
            ftable.cols.lastprint[:] = np.arange(len(ftable))
    else:
        print('Nothing to plot!')

    # Rename any .tmp files
    tmplist = glob.glob('{}{}/clusters/*.tmp'.format(opt.outputPath, opt.groupName))
    for tmp in tmplist:
        os.rename(tmp,tmp[0:-4])


### BOKEH OVERVIEW RENDERING ###

def plotTimelines(rtable, ftable, ttable, opt):

    """
    Wraps the creation of Bokeh timelines like overview.html and overview_recent.html

    rtable: Repeater table
    ftable: Families table
    ttable: Triggers table
    opt: Options object describing station/run parameters

    """

    dt = rtable.cols.startTimeMPL[:]
    fi = np.nanmean(rtable.cols.FI[:], axis=1)
    longevity = ftable.cols.longevity[:]
    famstarts = ftable.cols.startTime[:]
    alltrigs = ttable.cols.startTimeMPL[:]

    # Determine padding for hover bars (~1% of window range on each side)
    barpad = (max(alltrigs)-min(alltrigs))*0.01
    barpadr = opt.recplot*0.01
    barpadm = opt.mrecplot*0.01

    # Full overview
    renderBokehTimeline(ftable, dt, fi, longevity, famstarts, alltrigs, barpad,
        opt.plotformat, opt.dybin, opt.occurbin, min(alltrigs), opt.minplot,
        opt.fixedheight, '{}{}/overview.html'.format(opt.outputPath, opt.groupName),
        '{0} Overview'.format(opt.title), '<h1>{0}</h1>'.format(opt.title), opt)

    # Recent
    renderBokehTimeline(ftable, dt, fi, longevity, famstarts, alltrigs, barpadr,
        opt.plotformat, opt.hrbin/24, opt.recbin, max(alltrigs)-opt.recplot, 0,
        opt.fixedheight, '{}{}/overview_recent.html'.format(opt.outputPath,
        opt.groupName), '{0} Overview - Last {1:.1f} Days'.format(opt.title, opt.recplot),
        '<h1>{0} - Last {1:.1f} Days</h1>'.format(opt.title,opt.recplot), opt)

    # Meta overview (recent but all in tabs, to be referenced from one folder up)
    renderBokehTimeline(ftable, dt, fi, longevity, famstarts, alltrigs, barpadm,
        opt.plotformat.replace(',','+'), opt.mhrbin/24, opt.mrecbin,
        max(alltrigs)-opt.mrecplot, opt.mminplot, True,
        '{}{}/meta_recent.html'.format(opt.outputPath,opt.groupName),
        '{0} Overview - Last {1:.1f} Days'.format(opt.title, opt.mrecplot),(
        """<h1>{0} - Last {1:.1f} Days | <a href='overview.html' style='color:red'
        target='_blank'>Full Overview</a> | <a href="overview_recent.html"
        style="color:red" target="_blank">Recent</a></h1>""").format(
        opt.title,opt.mrecplot), opt)

def renderBokehTimeline(ftable, dt, fi, longevity, famstarts, alltrigs, barpad,
        plotformat, binsize, obinsize, mintime, minplot, fixedheight, filepath,
        htmltitle, divtitle, opt):

    """
    Generates a Bokeh timeline with given parameters

    ftable: Families table
    dt: Array containing times of repeaters
    fi: Array containing frequency index values of repeaters
    longevity: Array containing longevity values for all families
    famstarts: Array containing start times of all families
    alltrigs: Array containing times of all triggers
    barpad: Horizontal padding for hover bars (usually ~1% of window range)
    plotformat: Formatted list of plots to be rendered, separated by ',' or '+' where
        ',' denotes a new row and '+' groups the plots in tabs
    binsize: Width (in days) of time bins for rate plot
    obinsize: Width (in hours) Temporal bin size for occurrence plot
    mintime: Minimum time to plot; generates arrows if family extends earlier in time
    minplot: Minimum number of members in a family to include on occurence plot
    fixedheight: Boolean for whether the plot height should be the same height as
        the other plots (True), or variable in height (False)
    filepath: Output file location and name
    htmltitle: Title of html page
    divtitle: Title used in div container at top left of plots
    opt: Options object describing station/run parameters

    """

    plot_types = plotformat.replace('+',',').split(',')
    plots = []
    tabtitles = []
    maxtime = np.max(alltrigs)
    # Create each of the subplots specified in the configuration file
    for p in plot_types:

        if p == 'eqrate':
            # Plot EQ Rates (Repeaters and Orphans)
            plots.append(plotRate(alltrigs, dt, binsize, mintime, maxtime, opt))
            tabtitles = tabtitles+['Event Rate']

        elif p == 'fi':
            # Plot Frequency Index
            plots.append(plotFI(alltrigs, dt, fi, mintime, maxtime, opt))
            tabtitles = tabtitles+['FI']

        elif p == 'longevity':
            # Plot Cluster Longevity — This needs to be further functionalized!
            plots.append(plotLongevity(alltrigs, famstarts, longevity,
                                  mintime, maxtime, barpad, opt))
            tabtitles = tabtitles+['Longevity']

        elif p == 'occurrence':
            # Plot family occurrence
            plots.append(plotFamilyOccurrence(alltrigs, dt, famstarts, longevity,
                                  fi, ftable, mintime, maxtime, minplot,
                                  obinsize, barpad, 'rate', fixedheight, opt))
            tabtitles = tabtitles+['Occurrence (Color by Rate)']

        elif p == 'occurrencefi':
            # Plot family occurrence with color by FI
            plots.append(plotFamilyOccurrence(alltrigs, dt, famstarts, longevity,
                                  fi, ftable, mintime, maxtime, minplot,
                                  obinsize, barpad, 'fi', fixedheight, opt))
            tabtitles = tabtitles+['Occurrence (Color by FI)']

        else:
            print('{} is not a valid plot type. Moving on.'.format(p))

    # Set ranges
    for i in plots:
        i.x_range = plots[0].x_range

    # Add annotations
    if opt.anotfile != '':
        df = pd.read_csv(opt.anotfile)
        for j in plots:
            for row in df.itertuples():
                spantime = (datetime.datetime.strptime(row[1],
                    '%Y-%m-%dT%H:%M:%S')-datetime.datetime(1970,1,1)).total_seconds()
                j.add_layout(Span(location=spantime*1000, dimension='height',
                    line_color=row[2], line_width=row[3], line_dash=row[4],
                    line_alpha=row[5], level='underlay'))

    # Create output and save
    gridplot_items = [[Div(text=divtitle, width=1000, margin=(-40,5,-10,5))]]
    pnum = 0
    for pf in plotformat.split(','):
        # + joining options groups them into tabs
        if '+' in pf:
            tabs = []
            for pft in range(len(pf.split('+'))):
                tabs = tabs + [TabPanel(child=plots[pnum+pft],
                                     title=tabtitles[pnum+pft])]
            gridplot_items = gridplot_items + [[Tabs(tabs=tabs)]]
            pnum = pnum+pft+1
        else:
            gridplot_items = gridplot_items + [[plots[pnum]]]
            pnum = pnum+1

    o = gridplot(gridplot_items)
    output_file(filepath,title=htmltitle)
    save(o)


def bokehFigure(**kwargs):

    """
    Builds foundation for the bokeh subplots

    **kwargs can include any keyword argument that would be passable to a bokeh figure().
    See https://docs.bokeh.org/en/latest/docs/reference/plotting.html for a complete list.

    The main argument passed is usually 'title'. If they are not defined, 'tools',
    'width', 'height', and 'x_axis_type' are populated with default values.

    """

    # default values for bokehFigures
    if 'tools' not in kwargs:
        kwargs['tools'] = ['pan,box_zoom,reset,save,tap']
    if 'width' not in kwargs:
        kwargs['width'] = 1250
    if 'height' not in kwargs:
        kwargs['height'] = 250
    if 'x_axis_type' not in kwargs:
        kwargs['x_axis_type'] = 'datetime'

    # Create figure
    fig = figure(**kwargs)

    fig.grid.grid_line_alpha = 0.3
    fig.xaxis.axis_label = 'Date'
    fig.yaxis.axis_label = ''

    return fig


def plotRate(alltrigs, dt, binsize, mintime, maxtime, opt, useBokeh=True, ax=None):

    """
    Creates subplot for rate of orphans and repeaters

    alltrigs: Array containing times of all triggers
    dt: Array containing times of repeaters
    binsize: Width (in days) of each time bin
    mintime: Minimum time to be plotted
    maxtime: Maximum time to be plotted
    opt: Options object describing station/run parameters
    useBokeh: Boolean for whether to use Bokeh (default) or Matplotlib version
    ax: If using Matplotlib, the axis handle in which to plot

    Returns Bokeh figure handle or Matplotlib axis handle
    """

    dt_offset = binsize/2 # used to create the lines

    hr_days = 'Day Bin' if binsize>=1 else 'Hour Bin'
    if binsize >= 1:
        title = 'Repeaters vs. Orphans by {:.1f} Day Bin'.format(binsize)
    else:
        title = 'Repeaters vs. Orphans by {:.1f} Hour Bin'.format(binsize*24)

    # Create histogram of events/dybin
    histT, hT = np.histogram(alltrigs, bins=np.arange(mintime,
        maxtime+binsize, binsize))
    histR, hR = np.histogram(dt, bins=np.arange(mintime,
        maxtime+binsize, binsize))

    if useBokeh:
        fig = bokehFigure(title=title)
        fig.yaxis.axis_label = 'Events'
        fig.line(matplotlib.dates.num2date(hT[0:-1]+dt_offset), histT-histR,
            color='black', legend_label='Orphans')
        fig.line(matplotlib.dates.num2date(hR[0:-1]+dt_offset), histR, color='red',
            legend_label='Repeaters', line_width=2)
        fig.legend.location = 'top_left'

        return fig

    else:
        ax.plot(matplotlib.dates.num2date(hT[0:-1]+dt_offset), histT-histR, color='black',
            label='Orphans', lw=0.5)
        ax.plot(matplotlib.dates.num2date(hR[0:-1]+dt_offset), histR, color='red',
            label='Repeaters', lw=2)
        ax.set_title(title, loc='left', fontweight='bold')
        ax.set_ylabel('Events', style='italic')
        ax.set_xlabel('Date', style='italic')
        ax.legend(loc='upper left', frameon=False)

        return ax


def plotFI(alltrigs, dt, fi, mintime, maxtime, opt, useBokeh=True, ax=None):

    """
    Creates subplot for frequency index scatterplot

    alltrigs: Array containing times of all triggers
    dt: Array containing times of repeaters
    fi: Array containing frequency index values of repeaters
    mintime: Minimum time to be plotted
    maxtime: Maximum time to be plotted
    opt: Options object describing station/run parameters
    useBokeh: Boolean for whether to use Bokeh (default) or Matplotlib version
    ax: If using Matplotlib, the axis handle in which to plot

    Returns Bokeh figure handle or Matplotlib axis handle
    """

    if useBokeh:
        fig = bokehFigure(title='Frequency Index')
        fig.yaxis.axis_label = 'FI'
        # Always plot at least one invisible point
        fig.circle(matplotlib.dates.num2date(np.max(alltrigs)), 0, line_alpha=0,
            fill_alpha=0)
    else:
        ax.set_title('Frequency Index', loc='left', fontweight='bold')
        ax.set_ylabel('FI', style='italic')
        ax.set_xlabel('Date', style='italic')

    idxs = np.where((dt>=mintime) & (dt<=maxtime))[0]

    if useBokeh:
        fig.circle(matplotlib.dates.num2date(dt[idxs]), fi[idxs], color='red',
            line_alpha=0, size=3, fill_alpha=0.5)
        return fig
    else:
        ax.scatter(matplotlib.dates.num2date(dt[idxs]), fi[idxs], 2, c='red',
            alpha=0.25)
        # Don't know why, but need to call get_ylim() or y-limits sometimes freak out
        axlims = ax.get_ylim()
        return ax


def plotLongevity(alltrigs, famstarts, longevity, mintime, maxtime, barpad, opt,
    useBokeh=True, ax=None):

    """
    Creates subplot for longevity

    alltrigs: Array containing times of all triggers
    famstarts: Array containing start times of all families
    longevity: Array containing longevity values for all families
    mintime: Minimum time to be plotted; families starting before this time will not be
        plotted if they also end before this time, and will have left arrows if they end
        after it
    maxtime: Maximum time to be plotted
    barpad: Time padding so arrows have space
    opt: Options object describing station/run parameters
    useBokeh: Boolean for whether to use Bokeh (default) or Matplotlib version
    ax: If using Matplotlib, the axis handle in which to plot

    Returns Bokeh figure handle or Matplotlib axis handle
    """

    if useBokeh:
        fig = bokehFigure(y_axis_type='log',
            y_range=[0.01, np.sort(alltrigs)[-1]-np.sort(alltrigs)[0]],
            title='Cluster Longevity')
        fig.yaxis.axis_label = 'Days'
        # Always plot at least one invisible point
        fig.circle(matplotlib.dates.num2date(np.max(alltrigs)), 1, line_alpha=0,
        fill_alpha=0)
    else:
        ax.set_title('Longevity', loc='left', fontweight='bold')
        ax.set_ylabel('Days', style='italic')
        ax.set_xlabel('Date', style='italic')

    # Plot Data
    for n in range(len(famstarts)):

        add_line, add_larrow, add_rarrow, x1, x2 = generateLines(mintime,
            maxtime, barpad, famstarts[n], longevity[n])

        # Draw a line for the longevity data (turns off if data don't fall within time
        # window) and draw an arrow if longevity line extends beyond the data window
        if add_line:

            if useBokeh:
                source = ColumnDataSource(dict(
                    x=np.array(
                    (matplotlib.dates.num2date(x1),
                    matplotlib.dates.num2date(x2))),
                    y=np.array((longevity[n],longevity[n]))))
                fig.add_glyph(source, Line(x='x', y='y', line_color='red',
                    line_alpha=0.5))
            else:
                ax.semilogy(np.array((matplotlib.dates.num2date(x1),
                    matplotlib.dates.num2date(x2))),
                    np.array((longevity[n],longevity[n])), 'red', alpha=0.75, lw=0.5)

            if add_larrow:
                if useBokeh:
                    fig.add_layout(Arrow(end=VeeHead(size=5, fill_color='red',
                        line_color='red', line_alpha=0.5), line_alpha=0,
                        x_start=matplotlib.dates.num2date(famstarts[n]+longevity[n]),
                        x_end=matplotlib.dates.num2date(mintime-barpad),
                        y_start=longevity[n], y_end=longevity[n]))
                else:
                    ax.annotate('', xy=(matplotlib.dates.num2date(mintime-barpad),
                        longevity[n]),xytext=(matplotlib.dates.num2date(mintime-2*barpad),
                        longevity[n]), arrowprops=dict(arrowstyle='<-', color='red',
                        alpha=0.75))

            if add_rarrow:
                ax.annotate('', xy=(matplotlib.dates.num2date(maxtime+barpad),
                    longevity[n]), xytext=(matplotlib.dates.num2date(maxtime+2*barpad),
                    longevity[n]), arrowprops=dict(arrowstyle='<-', color='red',
                    alpha=0.75))

    if useBokeh:
        return fig
    else:
        return ax


def plotFamilyOccurrence(alltrigs, dt, famstarts, longevity, fi, ftable, mintime, maxtime,
    minplot, binsize, barpad, colorby, fixedheight, opt, useBokeh=True, ax=None):

    """
    Creates subplot for family occurrence

    alltrigs: Array containing times of all triggers
    dt: Array containing times of repeaters
    famstarts: Array containing start times of all families
    longevity: Array containing longevity values for all families
    fi: Array containing frequency index values of repeaters
    ftable: Families table
    mintime: Minimum time to be plotted; families starting before this time will not be
        plotted if they also end before this time, and will have left arrows if they end
        after it
    maxtime: Maximum time to be plotted
    minplot: Minimum number of members in a family to be included
    binsize: Width (in days) of each time bin
    barpad: Time padding so arrows have space
    colorby: What to use for color in histograms, 'rate' (YlOrRd) or 'fi' (coolwarm)
    fixedheight: Boolean for whether the plot height should be the same height as
        the other plots (True), or variable in height (False)
    opt: Options object describing station/run parameters
    useBokeh: Boolean for whether to use Bokeh (default) or Matplotlib version
    ax: If using Matplotlib, the axis handle in which to plot

    Returns Bokeh figure handle or Matplotlib axis handle
    """

    if useBokeh:
        fig = bokehFigure(tools=[createHoverTool(),'pan,box_zoom,reset,save,tap'],
            title='Occurrence Timeline', height=250, width=1250)
        fig.yaxis.axis_label = 'Cluster by Date' + (
            ' ({}+ Members)'.format(minplot) if minplot>0 else '')
        # Always plot at least one invisible point
        fig.circle(matplotlib.dates.num2date(np.max(alltrigs)), 0, line_alpha=0,
            fill_alpha=0)
    else:
        ax.set_title('Occurrence Timeline', loc='left', fontweight='bold')
        ax.set_ylabel('Cluster by Date' + (
            ' ({}+ Members)'.format(minplot) if minplot>2 else ''), style='italic')
        ax.set_xlabel('Date', style='italic')

    # Steal colormap (len=256) from matplotlib
    if colorby is 'rate':
        colormap = matplotlib.cm.get_cmap('YlOrRd')
    elif colorby is 'fi':
        colormap = matplotlib.cm.get_cmap('coolwarm')
    else:
        print('Unrecognized colorby choice, defaulting to rate')
        colorby = 'rate'
        colormap = matplotlib.cm.get_cmap('YlOrRd')
    bokehpalette = [matplotlib.colors.rgb2hex(m) for m in colormap(
        np.arange(colormap.N)[::-1])]

    n = 0
    for clustNum in range(ftable.attrs.nClust):

        members = np.fromstring(ftable[clustNum]['members'], dtype=int, sep=' ')

        # Create histogram of events/hour
        hist, h = np.histogram(dt[members], bins=np.arange(min(dt[members]),
            max(dt[members]+binsize), binsize))
        if useBokeh:
            d1 = matplotlib.dates.num2date(h[np.where(hist>0)])
            d2 = matplotlib.dates.num2date(h[np.where(hist>0)]+binsize)
        else:
            d1 = h[np.where(hist>0)]

        if colorby is 'rate':
            histlog = np.log10(hist[hist>0])
            if binsize >= 1:
                ind = [int(min(255,255*(i/3))) for i in histlog]
            else:
                ind = [int(min(255,255*(i/2))) for i in histlog]
        elif colorby is 'fi':
            h = h[np.where(hist>0)]
            hist = hist[hist>0]
            fisum = np.zeros(len(hist))
            # Loop through bins to get summed fi
            for i in range(len(hist)):
                # Find indicies of dt[members] within bins
                idxs = np.where(np.logical_and(dt[members]>=h[i],
                                               dt[members]<h[i]+binsize))
                # Sum fi for those events
                fisum[i] = np.sum(fi[members[idxs]])
            # Convert to mean fi
            histfi = fisum/hist
            ind = [int(max(min(255,255*(i-opt.fispanlow)/(opt.fispanhigh-opt.fispanlow)),
                                0)) for i in histfi]

        colors = [bokehpalette[i] for i in ind]

        if len(dt[members]) >= minplot:

            if max(dt[members])>mintime:

                add_line, add_larrow, add_rarrow, x1, x2 = generateLines(mintime,
                    maxtime, barpad, famstarts[clustNum], longevity[clustNum])

                if add_line:
                    if useBokeh:
                        source = ColumnDataSource(dict(
                            x=np.array(
                            (matplotlib.dates.num2date(x1),
                            matplotlib.dates.num2date(x2))),
                            y=np.array((n,n))))
                        fig.add_glyph(source, Line(x='x', y='y', line_color='black'))
                    else:
                        ax.plot(np.array((matplotlib.dates.num2date(x1),
                            matplotlib.dates.num2date(x2))),
                            np.array((n,n)), 'black', lw=0.5, zorder=0)

                    if add_larrow:
                        if useBokeh:
                            fig.add_layout(Arrow(end=VeeHead(size=5, fill_color='black',
                                line_color='black'), line_alpha=0,
                                x_start=matplotlib.dates.num2date(
                                famstarts[clustNum]+longevity[clustNum]),
                                x_end=matplotlib.dates.num2date(mintime-barpad),
                                y_start=n, y_end=n))
                        else:
                            ax.annotate('', xy=(matplotlib.dates.num2date(
                                mintime-barpad),n),xytext=(matplotlib.dates.num2date(
                                mintime-2*barpad),n), arrowprops=dict(arrowstyle='<-',
                                color='black', alpha=1))

                    if add_rarrow:
                        ax.annotate('', xy=(matplotlib.dates.num2date(maxtime+barpad),
                            n), xytext=(matplotlib.dates.num2date(maxtime+2*barpad),
                            n), arrowprops=dict(arrowstyle='<-', color='black',
                            alpha=1))

                # Add boxes
                if useBokeh:
                    idx = np.where(h[np.where(hist>0)[0]]>mintime)[0]
                    fig.quad(top=n+0.3, bottom=n-0.3,
                        left=np.array(d1)[idx],
                        right=np.array(d2)[idx],
                        color=np.array(colors)[idx])
                else:
                    # Potentially slow if many patches, but at least functional...
                    for i in range(len(d1)):
                        x = matplotlib.dates.num2date(np.array(d1)[i])
                        w = timedelta(binsize)
                        if (x >= matplotlib.dates.num2date(mintime)) and (
                            x <= matplotlib.dates.num2date(maxtime)):
                            ax.add_patch(matplotlib.patches.Rectangle((x,n-0.3),
                                w,0.6,facecolor=colors[i],edgecolor=None,fill=True))
                            if x+w > matplotlib.dates.num2date(x2):
                                x2 = np.array(d1)[i]+binsize

                # Add label
                if useBokeh:
                    label = Label(x=max(d2), y=n, text='  {}'.format(len(dt[members])),
                        text_font_size='9pt', text_baseline='middle')
                    fig.add_layout(label)
                else:
                    ax.annotate('  {}'.format(len(dt[members])), (
                        matplotlib.dates.num2date(x2),n), va='center', ha='left')

                if useBokeh:
                    # Build source for hover patches
                    fnum = clustNum
                    if n == 0:
                        xs=[[matplotlib.dates.num2date(max(min(dt[members]),
                            mintime)-barpad),matplotlib.dates.num2date(max(min(
                            dt[members]),mintime)-barpad),matplotlib.dates.num2date(max(
                            dt[members])+barpad),matplotlib.dates.num2date(max(
                            dt[members])+barpad)]]
                        ys=[[n-0.5, n+0.5, n+0.5, n-0.5]]
                        famnum=[[fnum]]
                    else:
                        xs.append([
                            matplotlib.dates.num2date(max(min(dt[members]),
                            mintime)-barpad),matplotlib.dates.num2date(max(min(
                            dt[members]),mintime)-barpad),matplotlib.dates.num2date(
                            max(dt[members])+barpad),matplotlib.dates.num2date(max(
                            dt[members])+barpad)])
                        ys.append([n-0.5, n+0.5, n+0.5, n-0.5])
                        famnum.append([fnum])

                n = n+1

    if useBokeh:
        cloc1 = 85

        if (n > 0):
            # Patches allow hovering for image of core and cluster number
            source = ColumnDataSource(data=dict(xs=xs, ys=ys, famnum=famnum))
            fig.patches('xs', 'ys', source=source, name='patch', alpha=0,
                selection_fill_alpha=0, selection_line_alpha=0, nonselection_fill_alpha=0,
                nonselection_line_alpha=0)

            # Tapping on one of the patches will open a window to a file with more information
            # on the cluster in question.
            url = './clusters/@famnum.html'
            renderer = fig.select(name='patch')
            taptool = fig.select(type=TapTool)[0]
            taptool.names.append('patch')
            taptool.callback = OpenURL(url=url)

            if (n > 15) and not fixedheight:
                fig.height = n*15
                fig.y_range = Range1d(-1, n)
                cloc1 = n*15-165

        if colorby is 'rate':
                color_bar = ColorBar(color_mapper=determineColorMapper(binsize),
                    ticker=LogTicker(), border_line_color='#eeeeee', location=(7,cloc1),
                    orientation='horizontal', width=150, height=15,
                    title='Events per {}'.format(determineLegendText(binsize)),
                    padding=15, major_tick_line_alpha=0,
                    formatter=LogTickFormatter(min_exponent=4))
        elif colorby is 'fi':
                color_bar = ColorBar(color_mapper=determineColorMapperFI(opt),
                    border_line_color='#eeeeee', location=(7,cloc1),
                    orientation='horizontal', width=150, height=15,
                    title='Mean Frequency Index', padding=15,
                    major_tick_line_alpha=0)

        fig.add_layout(color_bar)

        return fig

    else:
        return ax


def determineLegendText(binsize):

    """
    Helper function to determine legend wording

    binsize: Width (in days) of each time bin

    """

    if binsize == 1/24:
        legtext = 'Hour'
    elif binsize == 1:
        legtext = 'Day'
    elif binsize == 7:
        legtext = 'Week'
    elif binsize < 2:
        legtext = '{} Hours'.format(binsize*24)
    else:
        legtext = '{} Days'.format(binsize)

    return legtext


def determineColorMapper(binsize):

    """
    Helper function to determine color map for occurrence plot based on bin size

    binsize: Width (in days) of each time bin

    """

    # Steal YlOrRd (len=256) colormap from matplotlib
    colormap = matplotlib.cm.get_cmap('YlOrRd')
    bokehpalette = [matplotlib.colors.rgb2hex(m) for m in colormap(
        np.arange(colormap.N)[::-1])]
    if binsize >= 1:
        color_mapper = LogColorMapper(palette=bokehpalette, low=1, high=1000)
    else:
        color_mapper = LogColorMapper(palette=bokehpalette, low=1, high=100)

    return color_mapper


def determineColorMapperFI(opt):

    """
    Helper function to determine color map for occurrencefi plot based on opt.fispan

    opt: Options object describing station/run parameters

    """

    # Steal YlOrRd (len=256) colormap from matplotlib
    colormap = matplotlib.cm.get_cmap('coolwarm')
    bokehpalette = [matplotlib.colors.rgb2hex(m) for m in colormap(
        np.arange(colormap.N)[::-1])]
    color_mapper = LinearColorMapper(palette=bokehpalette,
                                     low=opt.fispanlow, high=opt.fispanhigh)

    return color_mapper


def createHoverTool():

    """
    Helper function to create family hover preview

    opath: Relative path to run directory, in case these plots are to be placed
        outside of it

    """

    hover = HoverTool(
        tooltips="""
        <div>
        <div>
            <img src="./clusters/@famnum.png" style="height: 100px; width: 500px;
                vertical-align: middle;"/>
            <span style="font-size: 9px; font-family: Helvetica;">Cluster ID: </span>
            <span style="font-size: 12px; font-family: Helvetica;">@famnum</span>
        </div>
        </div>
        """, renderers=["patch"])

    return hover


def generateLines(mintime, maxtime, barpad, famstart, longev):

    """
    Helper function to generate arrows and line positions for occurrence and longevity
    timelines

    mintime: minimum time on timeline axes as matplotlib date
    maxtime: maximum time on timeline axes as matplotlib date
    barpad: width of padding for arrows in days
    famstart: start time of family as matplotlib date
    longev: longevity of family in days

    Returns logic for whether lines/arrows are plotted and their line start/end times
    """

    add_rarrow = False
    add_larrow = False
    add_line = False
    x1 = 0
    x2 = 0

    # Family starts after start of mintime and ends before maxtime
    if (mintime<=famstart) and (maxtime>=famstart+longev):
        add_line = True
        x1 = famstart
        x2 = famstart+longev

    # Family starts after start of mintime but first event is past maxtime
    elif (mintime<=famstart) and (maxtime<=famstart):
        add_line = False

    # Family starts after start of mintime but ends after maxtime
    elif (mintime<=famstart) and (maxtime<=famstart+longev):
        add_line = True
        add_rarrow = True
        x1 = famstart
        x2 = maxtime+barpad

    # Family starts before mintime, ends before maxtime, and ends after mintime
    elif (mintime>=famstart) and (maxtime>=famstart+longev) and (
                                                               mintime<=famstart+longev):
        add_line = True
        add_larrow = True
        x1 = mintime-barpad
        x2 = famstart+longev

    # Family starts before mintime and ends after maxtime
    elif (mintime>=famstart) and (maxtime<=famstart+longev):
        add_line = True
        add_larrow = True
        add_rarrow = True
        x1 = mintime-barpad
        x2 = maxtime+barpad

    return add_line, add_larrow, add_rarrow, x1, x2



### PDF OVERVIEW ###

def customPDFoverview(rtable, ftable, ttable, tmin, tmax, binsize, minmembers,
    occurheight, plotformat, opt):

    """
    Generate a static PDF version of the overview plot for publication

    rtable: Repeater table
    ftable: Families table
    ttable: Triggers table
    tmin: minimum time on timeline axes as matplotlib date (or 0 to use default tmin)
    tmax: maximum time on timeline axes as matplotlib date (or 0 to use default tmax)
    binsize: width of histogram bin in days
    minmembers: Minimum number of members per family to be included in occurrence timeline
    occurheight: Integer multiplier for how much taller than the other timelines the
        occurrence timeline should be; determines figure aspect ratio/size
    plotformat: Formatted list of plots to be rendered, separated by ','
    opt: Options object describing station/run parameters

    At some point, this will be further customizable with which subplots to include, etc.
    """

    dt = rtable.cols.startTimeMPL[:]
    fi = np.nanmean(rtable.cols.FI[:], axis=1)
    longevity = ftable.cols.longevity[:]
    famstarts = ftable.cols.startTime[:]
    alltrigs = ttable.cols.startTimeMPL[:]

    # Custom tmin/tmax functionality
    if tmin:
        mintime = tmin
    else:
        mintime = min(alltrigs)

    if tmax:
        maxtime = tmax
    else:
        maxtime = max(alltrigs)
    barpad = 0.01*(maxtime-mintime)

    plot_types = plotformat.replace('+',',').split(',')

    # Determine the height of the plot
    nsub = 0
    for p in plot_types:
        if 'occurrence' in p:
            nsub = nsub + occurheight
        else:
            nsub = nsub + 1
    figheight = 2*nsub+4

    # Hack a reference axis
    figref = plt.figure(figsize=(9,1))
    axref = figref.add_subplot(1,1,1)
    axref = plotRate(alltrigs, dt, binsize, mintime, maxtime, opt,
        useBokeh=False, ax=axref)

    fig = plt.figure(figsize=(9, figheight))

    pnum = 0
    for p in plot_types:

        if p == 'eqrate':
            ### Rate ###
            ax = fig.add_subplot(nsub, 1, pnum+1, sharex=axref)
            ax = plotPDFAnnotations(ax, mintime, maxtime, opt)
            ax = plotRate(alltrigs, dt, binsize, mintime, maxtime, opt,
                useBokeh=False, ax=ax)
            pnum = pnum + 1

        elif p == 'fi':
            ### FI ###
            ax = fig.add_subplot(nsub, 1, pnum+1, sharex=axref)
            ax = plotPDFAnnotations(ax, mintime, maxtime, opt)
            ax = plotFI(alltrigs, dt, fi, mintime, maxtime, opt,
                useBokeh=False, ax=ax)
            pnum = pnum + 1

        elif p == 'occurrence':
            ### Occurrence ###
            ax = fig.add_subplot(nsub, 1, (pnum+1, pnum+occurheight), sharex=axref)
            ax = plotPDFAnnotations(ax, mintime, maxtime, opt)
            ax = plotFamilyOccurrence(alltrigs, dt, famstarts, longevity, fi, ftable,
                mintime, maxtime, minmembers, binsize, barpad, 'rate', True, opt,
                useBokeh=False, ax=ax)
            addPDFColorbar(fig, figheight, pnum, nsub, 'rate', binsize, opt)
            pnum = pnum + occurheight

        elif p == 'occurrencefi':
            ### Occurrence ###
            ax = fig.add_subplot(nsub, 1, (pnum+1, pnum+occurheight), sharex=axref)
            ax = plotPDFAnnotations(ax, mintime, maxtime, opt)
            ax = plotFamilyOccurrence(alltrigs, dt, famstarts, longevity, fi, ftable,
                mintime, maxtime, minmembers, binsize, barpad, 'fi', True, opt,
                useBokeh=False, ax=ax)
            addPDFColorbar(fig, figheight, pnum, nsub, 'fi', binsize, opt)
            pnum = pnum + occurheight

        elif p == 'longevity':
            ### Longevity ###
            ax = fig.add_subplot(nsub, 1, pnum+1, sharex=axref)
            ax = plotPDFAnnotations(ax, mintime, maxtime, opt)
            ax = plotLongevity(alltrigs, famstarts, longevity, mintime, maxtime,
                barpad, opt, useBokeh=False, ax=ax)
            pnum = pnum + 1

        else:
            print('{} is not a valid plot type. Moving on.'.format(p))

    # Clean up and save
    plt.tight_layout()
    plt.savefig('{}{}/overview.pdf'.format(opt.outputPath, opt.groupName))
    plt.close(fig)


def addPDFColorbar(fig, figheight, pnum, nsub, colorby, binsize, opt):

    """
    Helper function to add a colorbar to PDF occurrence plots

    fig: Figure handle
    figheight: Total height of the figure
    pnum: Current subplot number
    nsub: Number of subplots
    colorby: Determines colormap to use
    binsize: If colorby is 'rate' determines limits
    opt: Options object describing station/run parameters

    """

    # Inset colorbar
    bottom = (nsub-pnum)/nsub - 0.9/figheight
    cax = fig.add_axes([0.1, bottom, 0.2, 0.2/figheight])
    if colorby is 'rate':
        cax.set_title('Events per {}'.format(determineLegendText(binsize)), loc='left',
            style='italic')
    else:
        cax.set_title('Mean Frequency Index', loc='left', style='italic')
    cax.get_yaxis().set_visible(False)
    gradient = np.linspace(0, 1, 1001)
    gradient = np.vstack((gradient, gradient))
    if colorby is 'rate':
        cax.imshow(gradient, aspect='auto', cmap='YlOrRd_r', interpolation='bilinear')
        if binsize >= 1:
            cax.set_xticks((0,333.3,666.6,1000))
            cax.set_xticklabels(('1','10','100','1000'))
        else:
            cax.set_xticks((0,500,1000))
            cax.set_xticklabels(('1','10','100'))
    else:
        cax.imshow(gradient, aspect='auto', cmap='coolwarm_r', interpolation='bilinear')
        cax.set_xticks((0,500,1000))
        cax.set_xticklabels((opt.fispanlow,np.mean((opt.fispanlow,opt.fispanhigh)),
            opt.fispanhigh))
    cax.set_frame_on(False)
    cax.tick_params(length=0)


def plotPDFAnnotations(ax, mintime, maxtime, opt):

    """
    Helper function to plot annotations

    ax: Axis handle
    mintime: minimum time on timeline axes as matplotlib date
    maxtime: maximum time on timeline axes as matplotlib date
    opt: Options object describing station/run parameters

    Returns ax with annotations (if any) plotted
    """

    if opt.anotfile != '':
        df = pd.read_csv(opt.anotfile)
        for row in df.itertuples():
            plotdate = matplotlib.dates.date2num(np.datetime64(row[1]))
            if (plotdate >= mintime) and (plotdate <= maxtime):
                ax.axvline(plotdate, color=row[2], lw=row[3], ls=row[4], alpha=row[5],
                    zorder=-1)

    return ax



### FAMILY PAGES ###

def plotCores(rtable, ftable, opt):

    """
    Plots core waveforms as .png for hovering in timeline and header for family pages

    rtable: Repeater table
    ftable: Families table
    opt: Options object describing station/run parameters

    """

    for n in range(len(ftable))[::-1]:
        if ftable.cols.lastprint[n] != n and ftable.cols.printme[n] == 0:
            os.rename('{}{}/clusters/{}.png'.format(opt.outputPath, opt.groupName,
                ftable.cols.lastprint[n]), '{}{}/clusters/{}.png.tmp'.format(
                opt.outputPath, opt.groupName, n))
            os.rename('{}{}/clusters/fam{}.png'.format(opt.outputPath, opt.groupName,
                ftable.cols.lastprint[n]), '{}{}/clusters/fam{}.png.tmp'.format(
                opt.outputPath, opt.groupName, n))

    cores = rtable[ftable.cols.core[:]]
    n = -1
    for r in cores:
        n = n+1
        if ftable.cols.printme[n] == 1:
            fig = plt.figure(figsize=(5, 1))
            ax = plt.Axes(fig, [0., 0., 1., 1.])
            ax.set_axis_off()
            fig.add_axes(ax)

            waveform = r['waveform'][opt.printsta*opt.wshape:(opt.printsta+1)*opt.wshape]
            tmp = waveform[max(0, r['windowStart']-int(
                opt.ptrig*opt.samprate)):min(opt.wshape,
                r['windowStart']+int(opt.atrig*opt.samprate))]
            dat = tmp[int(opt.ptrig*opt.samprate - opt.winlen*0.5):int(
                opt.ptrig*opt.samprate + opt.winlen*1.5)]/r['windowAmp'][opt.printsta]
            dat[dat>1] = 1
            dat[dat<-1] = -1

            ax.plot(dat,'k',linewidth=0.25)
            plt.autoscale(tight=True)
            plt.savefig('{}{}/clusters/{}.png'.format(opt.outputPath, opt.groupName, n),
                dpi=100)
            plt.close(fig)


def plotFamilies(rtable, ftable, ctable, opt):

    """
    Creates multi-paneled family plots for all families that need to be plotted. This
    function wraps plotSingleFamily() and outputs all files as .png.

    rtable: Repeater table
    ftable: Families table
    ctable: Correlation table
    opt: Options object describing station/run parameters

    Top row: Ordered waveforms, stacked FFT
    Seocond row: Timeline of amplitude
    Third row: Timeline of event spacing
    Last row: Correlation with time relative to best-correlated event (most measurements)

    """

    # Load into memory
    startTimeMPL = rtable.cols.startTimeMPL[:]
    windowAmp = rtable.cols.windowAmp[:][:,opt.printsta]
    windowStart = rtable.cols.windowStart[:]
    fi = rtable.cols.FI[:]
    ids = rtable.cols.id[:]
    id1 = ctable.cols.id1[:]
    id2 = ctable.cols.id2[:]
    ccc = ctable.cols.ccc[:]

    for cnum in range(ftable.attrs.nClust):

        if ftable.cols.printme[cnum] != 0:

            plotSingleFamily(rtable, ftable, ctable, startTimeMPL, windowAmp, windowStart,
                fi, ids, id1, id2, ccc, 'png', 100, cnum, 0, 0, opt)


def plotSingleFamily(rtable, ftable, ctable, startTimeMPL, windowAmp, windowStart, fi,
    ids, id1, id2, ccc, oformat, dpi, cnum, tmin, tmax, opt):

    """
    Creates a multi-paneled family plot for the specified family 'cnum'. This function
    allows some flexibility in the output format (e.g., .png, .pdf) as well as resolution.
    Many inputs are columns from rtable to reduce overhead back to the file when calling
    this function for many families.

    rtable: Repeater table
    ftable: Families table
    ctable: Correlation table
    startTimeMPL: startTimeMPL column from rtable
    windowAmp: windowAmp column from rtable for single station
    windowStart: windowStart column from rtable
    fi: frequency index column from rtable
    ids: id column from rtable
    id1: id1 column from ctable
    id2: id2 column from ctable
    ccc: correlation values from ctable
    oformat: output file format as a string (e.g., 'png' or 'pdf')
    dpi: dots per inch resolution of raster file
    cnum: cluster/family number to plot
    tmin: minimum time on timeline axes as matplotlib date (or 0 to use default tmin)
    tmax: maximum time on timeline axes as matplotlib date (or 0 to use default tmax)
    opt: Options object describing station/run parameters

    Top row: Ordered waveforms, stacked FFT
    Seocond row: Timeline of amplitude
    Third row: Timeline of event spacing
    Last row: Correlation with time relative to best-correlated event (most measurements),
        with core event in black and events with missing correlation values as open
        circles (either were never correlated or were below threshold)

    """

    fam = np.fromstring(ftable[cnum]['members'], dtype=int, sep=' ')
    core = ftable[cnum]['core']

    # Station names
    stas = opt.station.split(',')
    chas = opt.channel.split(',')

    # Prep catalog
    catalogind = np.argsort(startTimeMPL[fam])
    catalog = startTimeMPL[fam][catalogind]
    spacing = np.diff(catalog)*24
    coreind = np.where(fam==core)[0][0]

    fig = plt.figure(figsize=(10, 12))

    # Plot waveforms
    ax1 = fig.add_subplot(9, 3, (1,8))

    # If only one station, plot all aligned waveforms
    if opt.nsta==1:

        famtable = rtable[fam]
        n=-1
        data = np.zeros((len(fam), int(opt.winlen*2)))
        for r in famtable:
            n = n+1
            waveform = r['waveform'][0:opt.wshape]
            tmp = waveform[max(0, windowStart[fam[n]]-int(
                opt.ptrig*opt.samprate)):min(opt.wshape,
                windowStart[fam[n]]+int(opt.atrig*opt.samprate))]
            try:
                ewarr = tmp[int(opt.ptrig*opt.samprate - opt.winlen*0.5):int(
                    opt.ptrig*opt.samprate + opt.winlen*1.5)]/windowAmp[fam[n]]
                data[n, :ewarr.shape[0]] = ewarr
            except (ValueError, Exception):
                print('Error in printing family {}, moving on...'.format(cnum))
        if len(fam) > 12:
            ax1.imshow(data, aspect='auto', vmin=-1, vmax=1, cmap='RdBu',
                interpolation='nearest', extent=[-1*opt.winlen*0.5/opt.samprate,
                opt.winlen*1.5/opt.samprate, n + 0.5, -0.5])
            tvec = [-1*opt.winlen*0.5/opt.samprate, opt.winlen*1.5/opt.samprate]
        else:
            tvec = np.arange(
                -opt.winlen*0.5/opt.samprate,opt.winlen*1.5/opt.samprate,
                1/opt.samprate)
            for o in range(len(fam)):
                dat=data[o,:]
                dat[dat>1] = 1
                dat[dat<-1] = -1
                ax1.plot(tvec,dat/2-o,'k',linewidth=0.25)

    # Otherwise, plot cores and stacks from all stations
    else:

        r = rtable[core]
        famtable = rtable[fam]
        tvec = np.arange(-opt.winlen*0.5/opt.samprate,opt.winlen*1.5/opt.samprate,
            1/opt.samprate)
        for s in range(opt.nsta):

            dats = np.zeros((int(opt.winlen*2),))
            waveform = famtable['waveform'][:,s*opt.wshape:(s+1)*opt.wshape]
            for n in range(len(fam)):
                tmps = waveform[n, max(0, windowStart[fam[n]]-int(
                    opt.ptrig*opt.samprate)):min(opt.wshape,
                    windowStart[fam[n]]+int(
                    opt.atrig*opt.samprate))]/(famtable['windowAmp'][
                    n,s]+1.0/1000)
                tmps[tmps>1] = 1
                tmps[tmps<-1] = -1
                try:
                    dats = dats + tmps[int(opt.ptrig*opt.samprate -
                        opt.winlen*0.5):int(opt.ptrig*opt.samprate +
                        opt.winlen*1.5)]
                except ValueError:
                   pass
            dats = dats/(max(dats)+1.0/1000)
            dats[dats>1] = 1
            dats[dats<-1] = -1
            ax1.plot(tvec,dats-1.75*s,'r',linewidth=1)

            waveformc = r['waveform'][s*opt.wshape:(s+1)*opt.wshape]
            tmpc = waveformc[max(0, r['windowStart']-int(
                opt.ptrig*opt.samprate)):min(opt.wshape,
                r['windowStart']+int(opt.atrig*opt.samprate))]
            datc = tmpc[int(opt.ptrig*opt.samprate - opt.winlen*0.5):int(
                opt.ptrig*opt.samprate + opt.winlen*1.5)]/(
                r['windowAmp'][s]+1.0/1000)
            datc[datc>1] = 1
            datc[datc<-1] = -1
            ax1.plot(tvec,datc-1.75*s,'k',linewidth=0.25)
            ax1.text(np.min(tvec)-0.1,-1.75*s,'{0}\n{1}'.format(stas[s],chas[s]),
                horizontalalignment='right', verticalalignment='center')

    ax1.axvline(x=-0.1*opt.winlen/opt.samprate, color='k', ls='dotted')
    ax1.axvline(x=0.9*opt.winlen/opt.samprate, color='k', ls='dotted')
    ax1.get_yaxis().set_visible(False)
    ax1.set_xlim((np.min(tvec),np.max(tvec)))
    if opt.nsta > 1:
        ax1.set_ylim((-1.75*s-1,1))
    ax1.set_xlabel('Time Relative to Trigger (seconds)', style='italic')

    # Plot mean FFT
    ax2 = fig.add_subplot(9, 3, (3,9))
    ax2.set_xlabel('Frequency (Hz)', style='italic')
    ax2.get_yaxis().set_visible(False)
    r = rtable[core]
    famtable = rtable[fam]
    freq = np.linspace(0,opt.samprate/2,int(opt.winlen/2))
    fftc = np.zeros((int(opt.winlen/2),))
    fftm = np.zeros((int(opt.winlen/2),))
    for s in range(opt.nsta):
        fft = np.abs(np.real(r['windowFFT'][int(
            s*opt.winlen):int(s*opt.winlen+opt.winlen/2)]))
        fft = fft/(np.amax(fft)+1.0/1000)
        fftc = fftc+fft
        ffts = np.mean(np.abs(np.real(famtable['windowFFT'][:,int(
            s*opt.winlen):int(s*opt.winlen+opt.winlen/2)])),axis=0)
        fftm = fftm + ffts/(np.amax(ffts)+1.0/1000)
    ax2.plot(freq,fftm,'r', linewidth=1)
    ax2.plot(freq,fftc,'k', linewidth=0.25)
    ax2.set_xlim(0,opt.fmax*1.5)
    ax2.legend(['Stack','Core'], loc='upper right', frameon=False)

    # Set min/max for plotting
    if opt.amplims == 'family':
        windowAmpFam = windowAmp[fam[catalogind]]
        try:
            ymin = 0.5*np.min(windowAmpFam[np.nonzero(windowAmpFam)])
            ymax = 2*np.max(windowAmpFam)
        except ValueError:
            # Use global if all zeros
            ymin = 0.5*np.min(windowAmp[np.nonzero(windowAmp)])
            ymax = 2*np.max(windowAmp)
    else:
        # Use global maximum/minimum
        ymin = 0.5*np.min(windowAmp[np.nonzero(windowAmp)])
        ymax = 2*np.max(windowAmp)

    # Plot amplitude timeline
    ax3 = fig.add_subplot(9, 3, (10,15))
    ax3.plot_date(catalog, windowAmp[fam[catalogind]],
            'ro', alpha=0.5, markeredgecolor='r', markeredgewidth=0.5,
            markersize=3)
    ax3.plot_date(catalog[coreind], windowAmp[fam[catalogind]][coreind],
            'ko', markeredgecolor='k', markeredgewidth=0.5,
            markersize=3)
    if tmin and tmax:
        ax3.set_xlim(tmin, tmax)
    elif tmin:
        ax3.set_xlim(tmin, ax3.get_xlim()[1])
    elif tmax:
        ax3.set_xlim(ax3.get_xlim()[0], tmax)
    myFmt = matplotlib.dates.DateFormatter('%Y-%m-%d\n%H:%M')
    ax3.xaxis.set_major_formatter(myFmt)
    ax3.set_ylim(ymin, ymax)
    ax3.margins(0.05)
    ax3.set_ylabel('Amplitude (Counts)', style='italic')
    ax3.set_xlabel('Date', style='italic')
    ax3.set_yscale('log')

    # Plot spacing timeline
    ax4 = fig.add_subplot(9, 3, (16,21))
    ax4.plot_date(catalog[1:], spacing, 'ro', alpha=0.5, markeredgecolor='r',
        markeredgewidth=0.5, markersize=3)
    if coreind>0:
        ax4.plot_date(catalog[coreind], spacing[coreind-1], 'ko',
            markeredgecolor='k', markeredgewidth=0.5, markersize=3)
    if tmin and tmax:
        ax4.set_xlim(tmin, tmax)
    elif tmin:
        ax4.set_xlim(tmin, ax4.get_xlim()[1])
    elif tmax:
        ax4.set_xlim(ax4.get_xlim()[0], tmax)
    myFmt = matplotlib.dates.DateFormatter('%Y-%m-%d\n%H:%M')
    ax4.xaxis.set_major_formatter(myFmt)
    ax4.set_xlim(ax3.get_xlim())
    ax4.set_ylim(1e-3, max(spacing)*2)
    ax4.margins(0.05)
    ax4.set_ylabel('Time since previous event (hours)', style='italic')
    ax4.set_xlabel('Date', style='italic')
    ax4.set_yscale('log')

    # Plot correlation timeline
    idf = ids[fam]
    ix = np.where(np.in1d(id2,idf))
    C = np.eye(len(idf))
    r1 = [np.where(idf==xx)[0][0] for xx in id1[ix]]
    r2 = [np.where(idf==xx)[0][0] for xx in id2[ix]]
    C[r1,r2] = ccc[ix]
    C[r2,r1] = ccc[ix]
    Cprint = C[np.argmax(np.sum(C,0)),:]

    ax5 = fig.add_subplot(9, 3, (22,27))
    ax5.plot_date(catalog, Cprint, 'ro', alpha=0.5,
        markeredgecolor='r', markeredgewidth=0.5, markersize=3)
    ax5.plot_date(catalog[coreind], Cprint[coreind], 'ko',
        markeredgecolor='k', markeredgewidth=0.5, markersize=3)
    Cprint[Cprint<opt.cmin] = opt.cmin
    Cprint[Cprint>opt.cmin] = np.nan
    ax5.plot_date(catalog, Cprint, 'wo', alpha=0.5,
        markeredgecolor='r', markeredgewidth=0.5)
    ax5.plot_date(catalog[np.where(fam==core)[0][0]], Cprint[coreind], 'wo',
        markeredgecolor='k', markeredgewidth=0.5, markersize=3)
    if tmin and tmax:
        ax5.set_xlim(tmin, tmax)
    elif tmin:
        ax5.set_xlim(tmin, ax5.get_xlim()[1])
    elif tmax:
        ax5.set_xlim(ax5.get_xlim()[0], tmax)
    myFmt = matplotlib.dates.DateFormatter('%Y-%m-%d\n%H:%M')
    ax5.xaxis.set_major_formatter(myFmt)
    ax5.set_xlim(ax3.get_xlim())
    ax5.set_ylim(opt.cmin-0.02, 1.02)
    ax5.margins(0.05)
    ax5.set_ylabel('Cross-correlation coefficient',
                   style='italic')
    ax5.set_xlabel('Date', style='italic')

    plt.tight_layout()
    plt.savefig('{}{}/clusters/fam{}.{}'.format(opt.outputPath, opt.groupName,
        cnum, oformat), dpi=dpi)
    plt.close(fig)


def plotFamilyHTML(rtable, ftable, opt):

    """
    Creates the HTML for the individual family pages.

    rtable: Repeater table
    ftable: Families table
    opt: Options object describing station/run parameters

    HTML will hold navigation, images, and basic statistics. May also include location
    information if external catalog is queried.
    """

    # Load into memory
    startTime = rtable.cols.startTime[:]
    startTimeMPL = rtable.cols.startTimeMPL[:]
    windowStart = rtable.cols.windowStart[:]
    fi = rtable.cols.FI[:]

    for cnum in range(ftable.attrs.nClust):

        fam = np.fromstring(ftable[cnum]['members'], dtype=int, sep=' ')
        core = ftable[cnum]['core']

        # Prep catalog
        catalogind = np.argsort(startTimeMPL[fam])
        catalog = startTimeMPL[fam][catalogind]
        longevity = ftable[cnum]['longevity']
        spacing = np.diff(catalog)*24
        minind = fam[catalogind[0]]
        maxind = fam[catalogind[-1]]
        coreind = np.where(fam==core)[0][0]

        if ftable.cols.printme[cnum] != 0 or ftable.cols.lastprint[cnum] != cnum:
            if cnum>0:
                prev = "<a href='{0}.html'>&lt; Cluster {0}</a>".format(cnum-1)
            else:
                prev = " "
            if cnum<len(ftable)-1:
                next = "<a href='{0}.html'>Cluster {0} &gt;</a>".format(cnum+1)
            else:
                next = " "
            # Now write a simple HTML file to show image and catalog
            with open('{}{}/clusters/{}.html'.format(opt.outputPath, opt.groupName,
                     cnum), 'w') as f:
                f.write("""
                <html><head><title>{1} - Cluster {0}</title>
                </head><style>
                a {{color:red;}}
                body {{font-family:Helvetica; font-size:12px}}
                h1 {{font-size: 20px;}}
                </style>
                <body><center>
                {10} &nbsp; | &nbsp; {11}</br>
                <h1>Cluster {0}</h1>
                <img src="{0}.png" width=500 height=100></br></br>
                    Number of events: {2}</br>
                    Longevity: {5:.2f} days</br>
                    Mean event spacing: {7:.2f} hours</br>
                    Median event spacing: {8:.2f} hours</br>
                    Mean Frequency Index: {9:.2f}<br></br>
                    First event: {3}</br>
                    Core event: {6}</br>
                    Last event: {4}</br>
                <img src="fam{0}.png"></br>
                """.format(cnum, opt.title, len(fam), (UTCDateTime(
                    startTime[minind]) + windowStart[minind]/opt.samprate).isoformat(),
                    (UTCDateTime(startTime[maxind]) + windowStart[
                    maxind]/opt.samprate).isoformat(), longevity, (UTCDateTime(
                    startTime[core]) + windowStart[core]/opt.samprate).isoformat(),
                    np.mean(spacing), np.median(spacing), np.mean(np.nanmean(fi[fam],
                    axis=1)),prev,next))

                if opt.checkComCat:
                    checkComCat(rtable, ftable, cnum, f, startTime, windowStart, opt)

                f.write("""
                </center></body></html>
                """)


def checkComCat(rtable, ftable, cnum, f, startTime, windowStart, opt):
    """
    Checks repeater trigger times with projected arrival times from ANSS Comprehensive
    Earthquake Catalog (ComCat) and writes these to HTML and image files. Will also
    check NCEDC catalog if location is near Northern California.

    rtable: Repeater table
    ftable: Families table
    cnum: cluster number to check
    f: HTML file to write to
    startTime: startTime column from rtable (convenience)
    windowStart: windowStart column from rtable (convenience)
    opt: Options object describing station/run parameters

    Traces through iasp91 global velocity model; checks for local, regional, and
    teleseismic matches for limited set of phase arrivals
    """

    pc = ['Potential', 'Conflicting']
    model = TauPyModel(model="iasp91")
    mc = 0
    n = 0
    l = 0
    stalats = np.array(opt.stalats.split(',')).astype(float)
    stalons = np.array(opt.stalons.split(',')).astype(float)
    latc = np.mean(stalats)
    lonc = np.mean(stalons)

    if opt.matchMax > 0:
        windowAmp = rtable.cols.windowAmp[:][:,opt.printsta]

    members = np.fromstring(ftable[cnum]['members'], dtype=int, sep=' ')
    if opt.matchMax == 0 or opt.matchMax > len(members):
        order = np.argsort(startTime[members])
        matchstring = ('</br><b>ComCat matches (all events):</b></br>'
            '<div style="overflow-y: auto; height:100px; width:1200px;">')
    else:
        nlargest = np.argsort(windowAmp[members])[::-1][:opt.matchMax]
        members = members[nlargest]
        order = np.argsort(startTime[members])
        matchstring = ('</br><b>ComCat matches ({} largest events):</b></br>'
            '<div style="overflow-y: auto; height:100px; width:1200px;">').format(
            opt.matchMax)

    for m in members[order]:
        t = UTCDateTime(startTime[m])+windowStart[m]/opt.samprate
        cc_url = ('http://earthquake.usgs.gov/fdsnws/event/1/query?'
                  'starttime={}&endtime={}&format=text').format(t-1800,t+30)
        try:
            comcat = pd.read_csv(cc_url,delimiter='|')
            otime = comcat['Time'].tolist()
            lat = comcat['Latitude'].tolist()
            lon = comcat['Longitude'].tolist()
            dep = comcat['Depth/km'].tolist()
            mag = comcat['Magnitude'].tolist()
            place = comcat['EventLocationName'].tolist()
        except (urllib.error.HTTPError, urllib.error.URLError):
            otime = []
            lat = []
            lon = []
            dep = []
            mag = []
            place = []

        # Check if near Northern California, then go to NCEDC for additional events but
        # for shorter time interval
        if latc > 34 and latc < 42 and lonc > -124 and lonc < -116:
            cc_urlnc = ('http://ncedc.org/fdsnws/event/1/query?'
                        'starttime={}&endtime={}&format=text').format((t-60).isoformat(),
                        (t+30).isoformat())
            try:
                ncedc = pd.read_csv(cc_urlnc,delimiter='|')
                otime.extend(ncedc[' Time '].tolist())
                lat.extend(ncedc[' Latitude '].tolist())
                lon.extend(ncedc[' Longitude '].tolist())
                dep.extend(ncedc[' Depth/km '].tolist())
                mag.extend(ncedc[' Magnitude '].tolist())
                place.extend(ncedc[' EventLocationName'].tolist())
            except (ValueError, urllib.error.HTTPError, urllib.error.URLError):
                pass

        n0 = 0
        for c in range(len(otime)):
            deg = locations2degrees(lat[c],lon[c],latc,lonc)
            dt = t-UTCDateTime(otime[c])

            if deg <= opt.locdeg:
                mc += 1
                if np.remainder(mc,100) == 0:
                    model = TauPyModel(model="iasp91")
                arrivals = model.get_travel_times(source_depth_in_km=max(0,dep[c]),
                    distance_in_degree=deg, phase_list=['p','s','P','S'])
                if len(arrivals) > 0:
                    pt = np.zeros((len(arrivals),))
                    pname = []
                    for a in range(len(arrivals)):
                        pt[a] = arrivals[a].time - dt
                        pname.append(arrivals[a].name)
                    if np.min(abs(pt)) < opt.serr:
                        amin = np.argmin(abs(pt))
                        matchstring+=('{} local match: {} ({:5.3f}, {:6.3f}) {:3.1f}km '
                            'M{:3.2f} - {} - ({}) {:4.2f} s</br>').format(pc[n0],otime[c],
                            lat[c],lon[c],dep[c],mag[c],place[c],pname[amin],pt[amin])
                        n0 = 1
                        l = l+1
                        if l == 1:
                            llats = np.array(lat[c])
                            llons = np.array(lon[c])
                            ldeps = np.array(dep[c])
                        else:
                            llats = np.append(llats,lat[c])
                            llons = np.append(llons,lon[c])
                            ldeps = np.append(ldeps,dep[c])
            elif deg <= opt.regdeg and mag[c] >= opt.regmag:
                mc += 1
                if np.remainder(mc,100) == 0:
                    model = TauPyModel(model="iasp91")
                arrivals = model.get_travel_times(source_depth_in_km=max(0,dep[c]),
                    distance_in_degree=deg, phase_list=['p','s','P','S','PP','SS'])
                if len(arrivals) > 0:
                    pt = np.zeros((len(arrivals),))
                    pname = []
                    for a in range(len(arrivals)):
                        pt[a] = arrivals[a].time - dt
                        pname.append(arrivals[a].name)
                    if np.min(abs(pt)) < opt.serr:
                        amin = np.argmin(abs(pt))
                        matchstring+=('<div style="color:red">{} regional match: {} '
                            '({:5.3f}, {:6.3f}) {:3.1f}km M{:3.2f} - {} - ({}) {:4.2f} '
                            's</div>').format(pc[n0],otime[c],lat[c],lon[c],dep[c],
                            mag[c],place[c],pname[amin],pt[amin])
                        n0 = 1
            elif deg > opt.regdeg and mag[c] >= opt.telemag:
                mc += 1
                if np.remainder(mc,100) == 0:
                    model = TauPyModel(model="iasp91")
                arrivals = model.get_travel_times(source_depth_in_km=max(0,dep[c]),
                    distance_in_degree=deg, phase_list=['P','S','PP','SS','PcP','ScS',
                        'PKiKP','PKIKP'])
                if len(arrivals) > 0:
                    pt = np.zeros((len(arrivals),))
                    pname = []
                    for a in range(len(arrivals)):
                        pt[a] = arrivals[a].time - dt
                        pname.append(arrivals[a].name)
                    if np.min(abs(pt)) < opt.serr:
                        amin = np.argmin(abs(pt))
                        matchstring+=('<div style="color:red">{} teleseismic match: {} '
                            '({:5.3f}, {:3.1f}) {:4.2f}km M{:3.2f} - {} - ({}) {:4.2f} '
                            's</div>').format(pc[n0],otime[c],lat[c],lon[c],dep[c],
                            mag[c],place[c],pname[amin],pt[amin])
                        n0 = 1
        if n0>1:
            n = n+1
        else:
            n = n+n0
    if n>0:
        matchstring+='</div>'
        matchstring+='Total potential matches: {}</br>'.format(n)
        matchstring+='Potential local matches: {}</br>'.format(l)
        if l>0:
            # Make map centered on seismicity
            stamen_terrain = cimgt.StamenTerrain()
            fig = plt.figure()
            ax = fig.add_subplot(1, 1, 1, projection=stamen_terrain.crs)
            ax.set_extent([np.median(llons)-opt.locdeg/2,np.median(llons)+opt.locdeg/2,
                np.median(llats)-opt.locdeg/4,np.median(llats)+opt.locdeg/4],
                crs=ccrs.PlateCarree())
            # Shaded terrain
            ax.add_image(stamen_terrain, 11)

            # Set up ticks
            ax.set_xticks(np.arange(np.floor(10*(np.median(llons)-opt.locdeg/2))/10,
                np.ceil(10*(np.median(llons)+opt.locdeg/2))/10,0.1),
                crs=ccrs.PlateCarree())
            ax.set_yticks(np.arange(np.floor(10*(np.median(llats)-opt.locdeg/4))/10,
                np.ceil(10*(np.median(llats)+opt.locdeg/4))/10, 0.1),
                crs=ccrs.PlateCarree())
            ax.set_extent([np.median(llons)-opt.locdeg/2,np.median(llons)+opt.locdeg/2,
                np.median(llats)-opt.locdeg/4,np.median(llats)+opt.locdeg/4],
                crs=ccrs.PlateCarree())
            ax.xaxis.set_major_formatter(LongitudeFormatter())
            ax.yaxis.set_major_formatter(LatitudeFormatter())
            plt.yticks(rotation=90, va='center')

            # Seismicity in red (halo of white), stations open black triangles
            ax.scatter(llons, llats, s=20, marker='o', color='white',
                transform=ccrs.PlateCarree())
            ax.scatter(llons, llats, s=5, marker='o', color='red',
                transform=ccrs.PlateCarree())
            ax.scatter(stalons, stalats, marker='^', color='k', facecolors='None',
                transform=ccrs.PlateCarree())

            # 10 km scale bar
            sbllon = 0.05*(opt.locdeg)+np.median(llons)-opt.locdeg/2
            sbllat = 0.05*(opt.locdeg/2)+np.median(llats)-opt.locdeg/4
            sbelon = sbllon + np.arctan2(np.sin(np.pi/2)*np.sin(
                10./6378.)*np.cos(sbllat*np.pi/180.), np.cos(10./6378.)-np.sin(
                sbllat*np.pi/180.)*np.sin(sbllat*np.pi/180.))*180./np.pi
            ax.plot((sbllon, sbelon), (sbllat,sbllat), 'k-', transform=ccrs.PlateCarree(),
                lw=2)
            geodetic_transform = ccrs.PlateCarree()._as_mpl_transform(ax)
            text_transform = offset_copy(geodetic_transform, units='dots', y=5)
            ax.text((sbllon+sbelon)/2., sbllat, '10 km', ha='center',
                transform=text_transform)

            plt.title('{} potential local matches (~{:3.1f} km depth)'.format(l,
                np.mean(ldeps)))
            plt.tight_layout()
            plt.savefig('{}{}/clusters/map{}.png'.format(opt.outputPath, opt.groupName,
                cnum), dpi=100)
            plt.close()
            f.write('<img src="map{}.png"></br>'.format(cnum))
    else:
        matchstring+='No matches found</br></div>'
    f.write(matchstring)


def cleanHTML(oldnClust, newnClust, opt):

    """
    Removes HTML files from deleted/moved family pages.

    oldnClust: Previous number of clusters (ftable.attrs.nClust)
    newnClust: New number of clusters
    opt: Options object describing station/run parameters

    This function deletes removed family .html files that have fnum above the current
    maximum family number.
    """

    for fnum in range(newnClust, oldnClust):
        if os.path.exists('{}{}/clusters/{}.html'.format(opt.outputPath, opt.groupName,
                          fnum)):
            os.remove('{}{}/clusters/{}.html'.format(opt.outputPath, opt.groupName, fnum))


### USER-GENERATED ###

def plotReport(rtable, ftable, ctable, fnum, ordered, matrixtofile, opt):

    """
    Creates more detailed output plots for a single family

    rtable: Repeater table
    ftable: Families table
    ctable: Correlation table
    fnum: Family to be inspected
    ordered: 1 if members should be ordered by OPTICS, 0 if by time
    matrixtofile: 1 if correlation should be written to file
    opt: Options object describing station/run parameters

    """

    # Read in annotation file (if it exists)
    if opt.anotfile != '':
        df = pd.read_csv(opt.anotfile)

    # Set up variables
    fam = np.fromstring(ftable[fnum]['members'], dtype=int, sep=' ')
    startTimeMPL = rtable.cols.startTimeMPL[:]
    startTime = rtable.cols.startTime[:]
    windowStart = rtable.cols.windowStart[:]
    windowAmp = rtable.cols.windowAmp[:][:,opt.printsta]
    windowAmps = rtable.cols.windowAmp[:]
    fi = rtable.cols.FI[:]
    ids = rtable.cols.id[:]
    id1 = ctable.cols.id1[:]
    id2 = ctable.cols.id2[:]
    ccc = ctable.cols.ccc[:]
    core = ftable[fnum]['core']
    catalogind = np.argsort(startTimeMPL[fam])
    catalog = startTimeMPL[fam][catalogind]
    famcat = fam[catalogind]
    longevity = ftable[fnum]['longevity']
    spacing = np.diff(catalog)*24
    minind = fam[catalogind[0]]
    maxind = fam[catalogind[-1]]

    idf = ids[fam]
    ix = np.where(np.in1d(id2,idf))
    C = np.eye(len(idf))
    r1 = [np.where(idf==xx)[0][0] for xx in id1[ix]]
    r2 = [np.where(idf==xx)[0][0] for xx in id2[ix]]
    C[r1,r2] = ccc[ix]
    C[r2,r1] = ccc[ix]

    # Copy static preview image in case cluster changes
    shutil.copy('{}{}/clusters/{}.png'.format(opt.outputPath, opt.groupName, fnum),
                '{}{}/reports/{}-report.png'.format(opt.outputPath, opt.groupName, fnum))

    # Fill in full correlation matrix
    print('Computing full correlation matrix; this will take time if the family is large')
    famtable = rtable[famcat]
    Cind = C[catalogind,:]
    Cind = Cind[:,catalogind]
    Cfull = Cind.copy()
    for i in range(len(famcat)-1):
        for j in range(i+1,len(famcat)):
            if Cfull[i,j]==0:
                # Compute correlation
                cor, lag, nthcor = redpy.correlation.xcorr1x1(famtable['windowFFT'][i],
                    famtable['windowFFT'][j], famtable['windowCoeff'][i],
                    famtable['windowCoeff'][j], opt)
                Cfull[i,j] = cor
                Cfull[j,i] = cor

    ### BOKEH PLOTS
    oTOOLS = ['pan,box_zoom,reset,save,tap']

    # Amplitude vs. time on all stations with interactive show/hide
    # Set min/max for plotting
    if opt.amplims == 'family':
        windowAmpFam = windowAmps[fam[catalogind]][:]
        ymin = 0.25*np.amin(windowAmpFam[np.nonzero(windowAmpFam)])
        ymax = 4*np.amax(windowAmpFam)
    else:
        # Use global maximum
        ymin = 0.25*np.amin(windowAmps[np.nonzero(windowAmps)])
        ymax = 4*np.amax(windowAmps)

    o0 = figure(tools=oTOOLS, width=1250, height=250, x_axis_type='datetime',
                title='Amplitude with Time (Click name to hide)', y_axis_type='log',
                y_range=[ymin,ymax])
    o0.grid.grid_line_alpha = 0.3
    o0.xaxis.axis_label = 'Date'
    o0.yaxis.axis_label = 'Counts'
    if opt.anotfile != '':
        for row in df.itertuples():
            spantime = (datetime.datetime.strptime(row[1]
                ,'%Y-%m-%dT%H:%M:%S')-datetime.datetime(1970, 1, 1)).total_seconds()
            o0.add_layout(Span(location=spantime*1000, dimension='height',
                line_color=row[2], line_width=row[3], line_dash=row[4],
                line_alpha=row[5]))
    if opt.nsta <= 8:
        palette = all_palettes['YlOrRd'][9]
    else:
        palette = inferno(opt.nsta+1)
    for sta, staname in enumerate(opt.station.split(',')):
        o0.circle(matplotlib.dates.num2date(startTimeMPL[fam]), windowAmps[fam][:,sta],
            color=palette[sta], line_alpha=0, size=4, fill_alpha=0.5,
            legend_label='{}.{}'.format(staname,opt.channel.split(',')[sta]))
    o0.legend.location='bottom_left'
    o0.legend.orientation='horizontal'
    o0.legend.click_policy='hide'


    # Time since last event
    o1 = figure(tools=oTOOLS, width=1250, height=250, x_axis_type='datetime',
                title='Time since Previous Event', x_range=o0.x_range, y_axis_type='log',
                y_range=[1e-3, 2*np.max(spacing)])
    o1.grid.grid_line_alpha = 0.3
    o1.xaxis.axis_label = 'Date'
    o1.yaxis.axis_label = 'Interval (hr)'
    if opt.anotfile != '':
        for row in df.itertuples():
            spantime = (datetime.datetime.strptime(row[1]
                ,'%Y-%m-%dT%H:%M:%S')-datetime.datetime(1970, 1, 1)).total_seconds()
            o1.add_layout(Span(location=spantime*1000, dimension='height',
                line_color=row[2], line_width=row[3], line_dash=row[4],
                line_alpha=row[5]))
    o1.circle(matplotlib.dates.num2date(catalog[1:]), spacing, color='red',
        line_alpha=0, size=4, fill_alpha=0.5)

    # Cross-correlation wrt. core
    o2 = figure(tools=oTOOLS, width=1250, height=250, x_axis_type='datetime',
                title='Cross-correlation Coefficient with Core Event', x_range=o0.x_range,
                y_range=[0, 1.02])
    o2.grid.grid_line_alpha = 0.3
    o2.xaxis.axis_label = 'Date'
    o2.yaxis.axis_label = 'CCC'
    if opt.anotfile != '':
        for row in df.itertuples():
            spantime = (datetime.datetime.strptime(row[1]
                ,'%Y-%m-%dT%H:%M:%S')-datetime.datetime(1970, 1, 1)).total_seconds()
            o2.add_layout(Span(location=spantime*1000, dimension='height',
                line_color=row[2], line_width=row[3], line_dash=row[4],
                line_alpha=row[5]))
    o2.circle(matplotlib.dates.num2date(catalog), Cfull[np.where(famcat==core)[0],:][0],
        color='red', line_alpha=0, size=4, fill_alpha=0.5)

    # Combine and save
    o = gridplot([[o0],[o1],[o2]])
    output_file('{}{}/reports/{}-report-bokeh.html'.format(opt.outputPath, opt.groupName,
        fnum), title='{} - Cluster {} Detailed Report'.format(opt.title, fnum))
    save(o)

    ### OPTICS ORDERING (OPTIONAL)
    if ordered:
        # Order by OPTICS rather than by time
        D = 1-Cfull
        s = np.argsort(sum(D))[::-1]
        D = D[s,:]
        D = D[:,s]
        famcat = famcat[s]
        Cind = Cind[s,:]
        Cind = Cind[:,s]
        Cfull = Cfull[s,:]
        Cfull = Cfull[:,s]
        ttree = setOfObjects(D)
        prep_optics(ttree,1)
        build_optics(ttree,1)
        order = np.array(ttree._ordered_list)
        famcat = famcat[order]
        Cind = Cind[order,:]
        Cind = Cind[:,order]
        Cfull = Cfull[order,:]
        Cfull = Cfull[:,order]

    ### SAVE FULL CORRELATION MATRIX TO FILE
    if matrixtofile:
        np.save('{}{}/reports/0-Cfull.npy'.format(opt.outputPath, opt.groupName, fnum),
            Cfull)
        np.save('{}{}/reports/0-evTimes.npy'.format(opt.outputPath, opt.groupName, fnum),
            startTime[famcat])

    ### CORRELATION MATRIX
    fig = plt.figure(figsize=(14,5.4))
    ax1 = fig.add_subplot(1,2,1)
    cax = ax1.imshow(Cind, vmin=opt.cmin-0.05, cmap='Spectral_r')
    cbar = plt.colorbar(cax, ticks=np.arange(opt.cmin-0.05,1.05,0.05))
    tix = cbar.ax.get_yticklabels()
    tix[0] = 'Undefined'
    cbar.ax.set_yticklabels(tix)
    if ordered:
        plt.title('Stored Correlation Matrix (Ordered)', fontweight='bold')
    else:
        plt.title('Stored Correlation Matrix', fontweight='bold')
        if opt.anotfile!='':
            for anot in range(len(df)):
                hloc = np.interp(matplotlib.dates.date2num(
                    pd.to_datetime(df['Time'][anot])),startTimeMPL[fam][catalogind],
                    np.array(range(len(fam))))
                if hloc!=0:
                    ax1.axhline(np.floor(hloc)+0.5,color='k',
                        linewidth=df['Weight'][anot]/2.,linestyle=df['Line Type'][anot])
    ax2 = fig.add_subplot(1,2,2)
    cax2 = ax2.imshow(Cfull, vmin=opt.cmin-0.05, cmap='Spectral_r')
    cbar2 = plt.colorbar(cax2, ticks=np.arange(opt.cmin-0.05,1.05,0.05))
    tix = cbar2.ax.get_yticklabels()
    tix[0] = '< {:1.2f}'.format(opt.cmin-0.05)
    cbar2.ax.set_yticklabels(tix)
    if ordered:
        plt.title('Full Correlation Matrix (Ordered)', fontweight='bold')
    else:
        plt.title('Full Correlation Matrix', fontweight='bold')
        if opt.anotfile!='':
            for anot in range(len(df)):
                hloc = np.interp(matplotlib.dates.date2num(
                    pd.to_datetime(df['Time'][anot])),startTimeMPL[fam][catalogind],
                    np.array(range(len(fam))))
                if hloc!=0:
                    ax2.axhline(np.floor(hloc)+0.5,color='k',
                        linewidth=df['Weight'][anot]/2.,linestyle=df['Line Type'][anot])
    plt.tight_layout()
    plt.savefig('{}{}/reports/{}-reportcmat.png'.format(opt.outputPath, opt.groupName,
                                                         fnum), dpi=100)
    plt.close(fig)

    ### WAVEFORM IMAGES
    famtable = rtable[famcat]
    fig2 = plt.figure(figsize=(10, 12))

    for sta in range(opt.nsta):
        n = -1
        data = np.zeros((len(fam), int(opt.winlen*2)))
        ax = fig2.add_subplot(int(np.ceil((opt.nsta)/2.)), 2, sta+1)
        for r in famtable:
            if ordered:
                plt.title('{0}.{1} (Ordered)'.format(opt.station.split(',')[sta],
                          opt.channel.split(',')[sta]), fontweight='bold')
            else:
                plt.title('{0}.{1}'.format(opt.station.split(',')[sta],
                          opt.channel.split(',')[sta]), fontweight='bold')
                if opt.anotfile!='':
                    for anot in range(len(df)):
                        hloc = np.interp(matplotlib.dates.date2num(
                            pd.to_datetime(df['Time'][anot])),
                            startTimeMPL[fam][catalogind],np.array(range(len(fam))))
                        if hloc!=0:
                            ax.axhline(np.floor(hloc)+0.5,color='k',
                                linewidth=df['Weight'][anot]/2.,
                                linestyle=df['Line Type'][anot])
            n = n+1
            waveform = r['waveform'][sta*opt.wshape:(sta+1)*opt.wshape]
            tmp = waveform[max(0, windowStart[famcat[n]]-int(
                opt.ptrig*opt.samprate)):min(opt.wshape,
                windowStart[famcat[n]]+int(opt.atrig*opt.samprate))]
            data[n, :] = tmp[int(opt.ptrig*opt.samprate - opt.winlen*0.5):int(
                opt.ptrig*opt.samprate + opt.winlen*1.5)]/windowAmps[famcat[n]][sta]
        if len(fam) > 12:
            ax.imshow(data, aspect='auto', vmin=-1, vmax=1, cmap='RdBu',
                interpolation='nearest', extent=[-1*opt.winlen*0.5/opt.samprate,
                opt.winlen*1.5/opt.samprate, n + 0.5, -0.5])
        else:
            tvec = np.arange(
                -opt.winlen*0.5/opt.samprate,opt.winlen*1.5/opt.samprate,
                1/opt.samprate)
            for o in range(len(fam)):
                dat=data[o,:]
                dat[dat>1] = 1
                dat[dat<-1] = -1
                ax.plot(tvec,dat/2-o*0.75,'k',linewidth=0.5)
            plt.xlim([np.min(tvec),np.max(tvec)])
            plt.ylim([-o*0.75-0.5,0.5])
        ax.yaxis.set_visible(False)
        plt.xlabel('Time Relative to Trigger (seconds)', style='italic')
    plt.tight_layout()
    plt.savefig('{}{}/reports/{}-reportwaves.png'.format(opt.outputPath, opt.groupName,
                fnum), dpi=100)
    plt.close(fig2)

    ### HTML OUTPUT PAGE
    tstamp = UTCDateTime.now()
    with open('{}{}/reports/{}-report.html'.format(opt.outputPath, opt.groupName, fnum),
              'w') as f:
        f.write("""
        <html><head><title>{1} - Cluster {0} Detailed Report</title>
        </head><style>
        a {{color:red;}}
        body {{font-family:Helvetica; font-size:12px}}
        h1 {{font-size: 20px;}}
        </style>
        <body><center>
        <em>Last updated: {10}</em></br>
        <h1>Cluster {0} - Detailed Report</h1>
        <img src="{0}-report.png" width=500 height=100></br></br>
            Number of events: {2}</br>
            Longevity: {5:.2f} days</br>
            Mean event spacing: {7:.2f} hours</br>
            Median event spacing: {8:.2f} hours</br>
            Mean Frequency Index: {9:.2f}<br></br>
            First event: {3}</br>
            Core event: {6}</br>
            Last event: {4}</br>

            <img src='{11}-reportwaves.png'></br></br>

            <iframe src="{11}-report-bokeh.html" width=1350 height=800
            style="border:none"></iframe>

            </br>
            <img src='{11}-reportcmat.png'></br></br></br>

        """.format(fnum, opt.title, len(fam), (UTCDateTime(
            startTime[minind]) + windowStart[minind]/opt.samprate).isoformat(),
            (UTCDateTime(startTime[maxind]) + windowStart[
            maxind]/opt.samprate).isoformat(), longevity, (UTCDateTime(
            startTime[core]) + windowStart[core]/opt.samprate).isoformat(),
            np.mean(spacing), np.median(spacing), np.mean(np.nanmean(fi[fam],
            axis=1)),tstamp,fnum))

        f.write("""
        </center></body></html>
        """)


def createJunkPlots(jtable, opt):

    """
    Creates images of waveforms contained in the junk table with file names corresponding
    to the trigger time and the flag for the type of junk it was flagged as.

    jtable: Junk table
    opt: Options object describing station/run parameters

    """

    # Write out times of junk triggers
    printJunk(jtable, opt)

    for r in jtable:
        fig = plt.figure(figsize=(15, 0.5))
        ax = plt.Axes(fig, [0., 0., 1., 1.])
        ax.set_axis_off()
        fig.add_axes(ax)


        for s in range(opt.nsta):
            waveformc = r['waveform'][s*opt.wshape:(s+1)*opt.wshape]
            tmpc = waveformc[r['windowStart']:r['windowStart']+opt.wshape]
            datc = tmpc[int(opt.ptrig*opt.samprate - opt.winlen*0.5):int(
                opt.ptrig*opt.samprate + opt.winlen*1.5)]
            datc = datc/np.max(np.abs(datc)+1.0/1000)
            datc[datc>1] = 1
            datc[datc<-1] = -1
            if s == 0:
                dat = datc
            else:
                dat = np.append(dat,datc)

        ax.plot(dat,'k',linewidth=0.25)
        plt.autoscale(tight=True)
        plt.savefig('{}{}/junk/{}-{}.png'.format(opt.outputPath, opt.groupName,
            (UTCDateTime(r['startTime'])+opt.ptrig).strftime('%Y%m%d%H%M%S'),
            r['isjunk']), dpi=100)
        plt.close(fig)

