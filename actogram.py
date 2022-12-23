import os
import sys
import sqlite3
import argparse
from shutil import copy, rmtree

import glob
import numpy as np
import pandas as pd

from itertools import groupby
from scipy.ndimage import median_filter

import datetime
from datetime import timedelta
from datetime import datetime as dt

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
from matplotlib.ticker import FormatStrFormatter


plt.close('all'); plt.style.use('default')
for tick in ['xtick.minor.visible', 'ytick.minor.visible']:
    plt.rcParams[tick] = False

class Actography:

    def __init__(self, args):

        self.show = args.show
        self.save_csv = args.save_csv

        self.freq = args.freq
        self.norm = args.normalize
        self.dblur = args.daily_blur
        self.hblur = args.hourly_blur

        self.landscape = args.landscape
        self.printer_friendly = args.printer_friendly

        self.zz = None # wakefulness
        self.dd = None # day range
        self.h1 = None # 24 hour range
        self.h2 = None # 48 hour range

        self.act = None
        self.pdf = None
        self.timeshare = None

        self.sleeps = []

        self.df = pd.DataFrame() # activity dataframe (each row === site visit)
        self.binned_df = pd.DataFrame() # df binned by interval (e.g. 15 min)

        self.freq_intv = float(self.freq[:-1])/60
        self.freq_no = int(24*60/float(self.freq[:-1]))

        self.h1 = np.linspace(0, 24, self.freq_no, endpoint=False)
        self.h2 = np.linspace(0, 48, 2*self.freq_no, endpoint=False)

        self.end = dt.combine(dt.today() - timedelta(days=1), dt.max.time())

        # TODO fix this to query intelligently (i.e., ignore 5% of early days
        # if they are isolated from rest, use a cutoff like 90% of data

        if args.start == 'available': self.start = dt.fromisoformat('2000-01-01 00:00:00')
        elif args.start is not None: self.start = dt.fromisoformat(args.start)
        else: self.start = dt.fromisoformat('2000-01-01 00:00:00')

    def __call__(self):

        self.__main__()

    def __main__(self):

        os.makedirs('actograms/', exist_ok=True)

        self.ImportData(self)
        self.ProcessData(self)

        plot = self.PlotData(self)
        self.ExportData(self, plot)

    class ImportData:

        def __init__(self, act):
            super().__init__()
            self.act = act

            self.__main__()

        def __main__(self):

            self.lookup_history_filepaths()
            self.copy_history_to_temp_folder()
            self.import_history_to_working_memory()
            self.delete_temporary_history_folder()

        def lookup_history_filepaths(self):
                """ check which OS user is running script from, then 
                check typical file paths for popular browser history files """

                home = os.path.expanduser("~")

                if sys.platform == "darwin":  # Darwin == OSX
                    safari_src = os.path.join(home, 'Library/Safari/History.db')
                    chrome_src = os.path.join(home, 'Library/Application Support/Google/Chrome/Default/History')
                    firefox_src = None # TODO
                    edge_src = None # TODO

                elif sys.platform == "win32":
                    safari_src = None
                    chrome_src = home + '/AppData/Local/Google/Chrome/User Data/Default/History'
                    firefox_src = None # TODO
                    edge_src = home + '/AppData/Local/Microsoft/Edge/User Data/Default/History'

                else:
                    print('Sorry, having trouble with your operating system.')
                    sys.exit()

                self.history_loc_dict = {'safari':   [safari_src, 'History.db'],
                                         'chrome':   [chrome_src, 'History'],
                                         'firefox':  [firefox_src, 'History'],
                                         'edge':     [edge_src, 'History']
                                         }

        def copy_history_to_temp_folder(self):
            """ Iterate through each file referenced in the history_loc_dict 
            and copy to some temporary folder. This avoids direclty operating 
            on the user's broswers' history files. """

            for key, value in self.history_loc_dict.items():
                src, fname = value

                if src is not None:
                    self.copy_history_func(src, fname)


        def copy_history_func(self, src, fname, dst_folder='temp_history'):
            """ function to copy file at given file location to temporary folder"""

            os.makedirs(dst_folder, exist_ok=True)
            dst = os.path.join(dst_folder, fname)

            try:
                copy(src, dst)
                return dst

            except IOError as e:
                print("Unable to copy file. %s" % e)

            except FileNotFoundError:
                print('The file \'' + fname + '\' could not be found.')

            except Exception:
                print('Something went wrong, the file \'' +
                      fname + '\' was not loaded.')

        def import_history_to_working_memory(self):
            """ Imports all of the files in the temporary folder into working
                memory. Each browser's particular history file format is 
                standardized before concatenating to an overarching df"""

            for key, value in self.history_loc_dict.items():
                src, fname = value

                if src is not None:
                    if key == 'safari':
                        command_str = 'SELECT datetime(visit_time+978307200, "unixepoch",\
                                      "localtime") FROM history_visits ORDER BY visit_time DESC;'

                    elif key == 'chrome':
                        command_str = "SELECT datetime(last_visit_time/1000000-11644473600,\
                        'unixepoch','localtime'), url FROM urls ORDER BY last_visit_time DESC;"

                    elif key == 'firefox':
                        pass

                    elif key == 'edge':
                        command_str = "SELECT datetime(last_visit_time/1000000-11644473600,\
                        'unixepoch','localtime'), url FROM urls ORDER BY last_visit_time DESC;"

                    temp_src = os.path.join('temp_history', fname)
                    df = self._import_history_func(temp_src, command_str)
                    self.act.df = pd.concat([self.act.df, df])

        def delete_temporary_history_folder(self):
            """ Delete the temporary folder after files are copied into working 
            memory. No need to cache this temporary folder, unless looking to backup
            browser history data (in which case there are better alternatives) """

            if os.path.isdir('temp_history'):
                rmtree('temp_history')

        def _import_history_func(self, file_name, command_str):
            """ Function to open SQL styled history files and convert to a pandas
            DataFrame type. SQL objects are closed after copying to Pandas DF. """

            cnx = sqlite3.connect(file_name)
            df = pd.read_sql_query(command_str, cnx)
            cnx.commit()
            cnx.close()

            df.rename(inplace=True, columns={df.columns[0]: 'visit_time'})
            df = pd.to_datetime(df['visit_time'], errors='coerce').dropna()

            return df

    class ProcessData:

        def __init__(self, act):
            super().__init__()
            self.act = act

            self.pcm = None
            self.pdf = None
            self.tshare = None

            self.df = self.act.df
            self.binned_df = self.act.df

            self.__main__()

        def __main__(self):

            self.aggregate_visits_by_freq()
            self.pre_allocate_binned_df()
            self.clip_date_range() # TODO make timezone aware, add option for visualizing in either current tz or selected tz

            self.init_pcolormesh_args()
            self.apply_median_blurring()
            self.define_pcolormesh_args()

            self.check_continuous_sleep_times()
            self.define_subplot_args()

            self.pass_processed_data()

        def aggregate_visits_by_freq(self):
            """
            INPUT: pandas dataframe from private class variables

            OUTPUT: Nx1 pandas dataframe (not series) of binned visit histories

            DESCRIPTION: 
            Aggregate the M rows for each unique visit from self.df into some N 
            rows corresponding to all the time intervals (e.g. 5 min)
            in the input dataframe's date range. Output row values are the 
            number of visits within each time interval. """

            visits = pd.to_datetime(self.df.iloc[:, 0])
            self.df = pd.DataFrame({'visits': np.ones(len(visits))}, index=visits)
            self.df = self.df.resample(self.act.freq).agg({'visits': 'sum'})
            self.df = self.df.fillna(0)


        def pre_allocate_binned_df(self):

            """
            INPUT: binned visit histories from previous step (private class variable)

            OUTPUT: M x  binned dataframe of appropriate shape 

            DESCRIPTION: 
            Aggregate the M rows for each unique visit from self.df into some N 
            rows corresponding to all the time intervals (e.g. 5 min)
            in the input dataframe's date range. Output row values are the 
            number of visits within each time interval. 
            """

            bdf = pd.DataFrame(data=self.df, index=self.df.index)

            d1 = self.df.index.min().floor(freq='D') - timedelta(days=1)
            d2 = self.df.index.max().ceil(freq='D') - timedelta(days=1, seconds=1)
            days = pd.date_range(d1, d2, freq=self.act.freq)

            bdf = bdf.reindex(days, fill_value=0)
            bdf['x'], bdf['y'] = (lambda x: (x.date, x.time))(bdf.index)
            bdf.rename(columns={'visits': 'z'}, inplace=True)

            self.binned_df = bdf

        def clip_date_range(self):

            first_visit = self.df.ne(0).idxmax()[0]
            dt_first_visit = dt.combine(first_visit, dt.min.time())
            if self.act.start <= dt_first_visit: self.act_start = dt_first_visit

            bdf = self.binned_df
            bdf = bdf.fillna(0)
            bdf = bdf[bdf.index >= self.act.start]
            bdf = bdf[bdf.index <= self.act.end]

            self.act.dd = pd.unique(bdf.index.date)

            self.binned_df = bdf

        def init_pcolormesh_args(self):
            """ define the x, y and z (color) data structure for plotting later on"""

            z = self.binned_df['z'].T.values
            act_z = np.asarray(z.reshape(len(self.act.h1), -1, order='F'))

            self.pcm = {'x': None,
                        'y': None,
                        'z': act_z.astype(int)}


        def apply_median_blurring(self):
            """ apply blurring process to smooth out time away from the internet 
            at the daily level or one-off periods at the day-to-day level"""

            zz = self.pcm['z']

            if self.act.hblur: zz = median_filter(zz, size=(self.act.hblur, 1))
            if self.act.dblur: zz = median_filter(zz, size=(1, self.act.dblur))
            if self.act.norm:  zz = (zz>=1)

            self.pcm['z'] = zz.astype(float)

        def define_pcolormesh_args(self):

            xx, yy, zz = self.act.dd, self.act.h2, np.tile(self.pcm['z'], (2, 1))

            if not self.act.landscape:
                xx, yy = yy, xx
                zz = zz.T

            self.pcm = {'x': xx, 'y': yy, 'z': zz}
            self.act.act = self.pcm

        def define_subplot_args(self):

            dt = self.act.freq_intv

            ax_pdf = 0^self.act.landscape
            ax_ts = 1^self.act.landscape

            zz = self.pcm['z']

            _ = lambda x: pd.Series(x).rolling(window=7, min_periods=0).mean()
            offline_avg = _(24 - np.nansum(zz * dt/2, axis=ax_ts))
            sleeps_avg = _(self.act.sleeps)

            #days = pd.date_range(self.act.dd[0], self.act.dd[-1])
            #pdf = np.pad(pdf, (2,1), mode='edge')
            #offline_avg = np.pad(offline_avg, (1,2), mode='edge')
            #sleeps_avg = np.pad(sleeps_avg, (1,2), mode='edge')

            self.act.timeshare = [offline_avg, sleeps_avg]
            self.act.pdf = (lambda x: x/x.max())(np.nansum(zz, axis=ax_pdf))

        def pass_processed_data(self):

            self.act.df = self.df
            self.act.binned_df = self.binned_df

        def check_continuous_sleep_times(self):
            """
            INPUT: day vector (XX), binned search activity (ZZ)

            OUTPUT: vector with daily record for longest consecitive time offline 

            DESCRIPTION: 
            Takes vector of binary-encoded sleep-wake periods and tallies
            continuous stretches with zero-encoding (asleep) to a storage list. 

            Then appends largest element in storage list to a second output
            list equal in len to XX corresponding to longest offline periods. 

            Finally multiplies np array'ed output list with binning frequency 
            to estimate longest real-time duration spent offline in date range
            """
            temp = self.binned_df
            #xx, yy, zz = self.pcm
            days, awake = temp['x'], (temp['z'] > 0).values.astype(int)

            adhoc = pd.DataFrame(np.array([days, awake]).T, columns=['days', 'awake'])

            for idx, (_, v) in enumerate(list(adhoc.groupby('days')['awake'])):
                screen_breaks = [sum(not(i) for i in g) for _, g in groupby(v)]
                longest_break = np.array(screen_breaks).max() * self.act.freq_intv
                self.act.sleeps.append(longest_break)




    class PlotData:

        def __init__(self, act):

            super().__init__()
            self.act = act

            self.freq_no = self.act.freq_no
            self.landscape = self.act.landscape
            self.friendly = self.act.printer_friendly

            self.DPI = 450
            self.figsize = (8,6) if self.landscape else (7,8)

            self.px_size = tuple(map(lambda x: x*self.DPI, self.figsize))

            self.lw = 1/(len(self.act.h1))
            if len(self.act.h1) > 24*5: self.lw = 0

            horizontal = {'figsize': self.figsize,

                          'ax_pdf': [0, 0], 'ax_sleep': [1, 1],
                          'labels': ['Activity PDF', 'Time Offline (h)'],
                          'hratio': [1, 0.15], 'wratio': [0.1, 1],

                          'left':   0.1, 'right':  0.95,
                          'bottom': 0.05, 'top':    0.85,
                          'wspace': 0.12, 'hspace': 0.2,
                        }

            vertical = {'figsize': self.figsize,

                        'ax_pdf': [1, 1], 'ax_sleep': [0, 0],
                        'labels': ['Time Offline (h)', 'Activity PDF'],

                        'hratio': [1, 0.1], 'wratio': [0.2, 1],

                        'left':   0.10, 'right':  0.85,
                        'bottom': 0.05, 'top':    0.85,
                        'wspace': 0.22, 'hspace': 0.12,
                        }

            self.plot_params = horizontal if self.landscape else vertical

            self.__main__()


        def __main__(self):

            self.fig = self.plotter()

        def plotter(self):

            p = self.plot_params
            fig, fig_ax = plt.subplots(figsize=p['figsize'])

            plt.subplots_adjust(bottom=p['bottom'], top=p['top'],
                                left=p['left'], right=p['right'],
                                wspace=p['wspace'], hspace=p['hspace'])

            spec = gridspec.GridSpec(ncols=2, nrows=2,
                                     height_ratios = p['hratio'],
                                     width_ratios= p['wratio'])
            fig_ax.axis('off')

            ax_actogram = fig.add_subplot(spec[0, 1])
            ax_sleep = fig.add_subplot(spec[p['ax_sleep'][0], p['ax_sleep'][1]])
            ax_pdf = fig.add_subplot(spec[p['ax_pdf'][0], p['ax_pdf'][1]])
            ax_nul = fig.add_subplot(spec[1, 0])

            self.subplot_the_actogram(ax_actogram)
            self.subplot_the_timeshare(ax_sleep, ax_actogram)
            self.subplot_the_pdf(ax_pdf, ax_actogram)
            self.plot_subplot_titles(ax_nul, fig_ax)

            return fig


        def subplot_the_actogram(self, ax):

            cmap = 'binary' if self.friendly else 'binary_r'

            lbl = lambda _: '0h' if not _%24 else ''.join('0'+str(_%24))[-2:]

            xx, yy, zz = [_ for k,_ in self.act.act.items()]

            ax.pcolormesh(xx, yy, zz,
                          shading='auto', cmap=cmap, vmin=0,
                          ec='dimgrey', lw=self.lw, clip_on=False)

            if self.landscape:

                locator = mdates.AutoDateLocator(minticks=1, maxticks=4)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

                ax.tick_params(axis='x', direction='out')
                ax.set_xticks(ax.get_xticks())

                ax.set_yticks(np.arange(0, int(self.act.h2[-1]), 6))
                ax.set_yticklabels(lbl(_) for _ in ax.get_yticks())

                ax.invert_yaxis()

            else:

                locator = mdates.AutoDateLocator(minticks=1, maxticks=4)
                ax.yaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

                ax.tick_params(axis='y', direction='out')
                ax.set_yticks(ax.get_yticks())

                ax.set_xticks(np.arange(6, int(self.act.h2[-1]), 6))
                ax.set_xticklabels(lbl(_) for _ in ax.get_xticks())

                ax.yaxis.tick_left()
                ax.invert_yaxis()

            return ax


        def subplot_the_pdf(self, ax, ref_ax):

            x = self.act.h2
            pdf = self.act.pdf

            if self.landscape:

                ax.fill_betweenx(x, pdf, color='grey', alpha=0.3,lw=0,step='mid')

                ax.spines['top'].set_visible(False)
                ax.spines['left'].set_visible(False)

                ax.set_xlim([0, 1])
                ax.set_xticks(ax.get_xlim())
                ax.set_xticklabels(ax.get_xticks())
                ax.xaxis.set_major_formatter(FormatStrFormatter('%d'))

                ax.yaxis.tick_right()
                ax.set_yticklabels([])
                ax.set_yticks(ref_ax.get_yticks())
                ax.set_ylim(ref_ax.get_ylim())

                ax.invert_xaxis()

            else:

                ax.fill_between(x, pdf, color='grey', alpha=0.3,lw=0,step='mid')

                ax.spines['right'].set_visible(False)
                ax.spines['bottom'].set_visible(False)

                ax.set_ylim([0, 1])
                ax.yaxis.tick_left()
                ax.set_yticks(ax.get_ylim())
                ax.set_yticklabels(ax.get_yticks())
                ax.yaxis.set_major_formatter(FormatStrFormatter('%d'))

                ax.xaxis.tick_top()
                ax.set_xticklabels([])
                ax.set_xticks(ref_ax.get_xticks())
                ax.set_xlim(ref_ax.get_xlim())


                ax.invert_yaxis()

            return ax


        def subplot_the_timeshare(self, ax, ref_ax):

            x = self.act.dd
            y1, y2 = self.act.timeshare

            if self.landscape:

                ax.fill_between(x, y1, color='grey', alpha=0.3, lw=0, step='mid')
                ax.fill_between(x, y2, color='k', alpha=0.5, lw=0, step='mid')

                ax.axes.axhline(8, color='k', linestyle='--', lw=0.75)

                ax.spines['right'].set_visible(False)
                ax.spines['bottom'].set_visible(False)

                ax.set_yticks([0, 8, 24])
                ax.set_ylim(0, 24)

                ax.xaxis.tick_top()
                ax.set_xticklabels([])
                ax.set_xticks(ref_ax.get_xticks())
                ax.set_xlim(ref_ax.get_xlim())

                ax.invert_yaxis()

            else:

                ax.fill_betweenx(x, y1, color='grey', alpha=0.3, lw=0, step='mid')
                ax.fill_betweenx(x, y2, color='k', alpha=0.5, lw=0, step='mid')

                ax.axes.axvline(8, color='k', linestyle='--', lw=0.75)
    
                ax.spines['left'].set_visible(False)
                ax.spines['top'].set_visible(False)

                ax.set_xticks([0, 8, 24])
                ax.set_xlim(0, 24)

                ax.yaxis.tick_right()
                ax.set_yticklabels([])
                ax.set_yticks(ref_ax.get_yticks())
                ax.set_ylim(ref_ax.get_ylim())

                ax.invert_xaxis()

            return ax

        def plot_subplot_titles(self, ax, fig_ax):

            p = self.plot_params

            increments =int(60/(self.freq_no/(24)))

            if self.landscape:
                ax.text(1, 1+p['hspace']/2, p['labels'][0], ha='right')
                ax.text(1, p['hspace'], p['labels'][1], ha='right')

                s = ("Approximate sleep-wake periods, generated from time stamped "
                    "internet browser searches\nbetween {:%d-%b-%Y} and {:%d-%b-%Y}. "
                    "Increments of {} minutes.".format(self.act.dd[0], self.act.dd[-1], increments))

            else:
                ax.text(1, 1-p['hspace'], p['labels'][0], ha='right')
                ax.text(1, p['hspace']/2, p['labels'][1], ha='right')

                s = ("Approximate sleep-wake periods, generated from time stamped "
                    "internet browser searches between {:%d-%b-%Y} and {:%d-%b-%Y}. "
                    "Increments of {} minutes.".format(self.act.dd[0], self.act.dd[-1], increments))

            fig_ax.text(x=0, y=1.1, s='Double-Plotted Online Actogram',
                     ha='left', va='bottom', fontweight='bold', wrap=True)
            fig_ax.text(0, 1.09, s=s, ha='left', va='top', wrap=True)

            ax.axis('off')

    class ExportData:

        def __init__(self, act, plot):
            super().__init__()
            self.act = act
            self.plot = plot

            self.__main__()

        def __main__(self):

            if self.act.show: self.export_actogram()
            if self.act.save_csv: self.export_csv('visits')

        def export_actogram(self):

            fig = self.plot.fig

            orientation = 'horizontal' if self.act.landscape else 'vertical'
            fig.savefig('actograms/actogram_' + orientation +'_' +
                        dt.today().date().isoformat() + '.png', dpi=self.plot.DPI)

        def export_csv(self, filename):

            self.act.df.to_csv('temp.csv')

            size_most_recent = 0
            list_exports  = glob.glob('actograms/*.csv')

            if len(list_exports):
                most_recent = sorted(list_exports, key=os.path.getsize)[0]
                size_most_recent = os.path.getsize(most_recent)

            if os.path.getsize('temp.csv') >= size_most_recent:
                self.act.df.to_csv('actograms/' + filename + '.csv')
                os.remove('temp.csv')


def main():

    act = Actography(ARGS)
    act()

    return None

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--freq', type=str, action='store',default='15T')

    parser.add_argument('--start', type=str, action='store', default='2021-08-01')
    parser.add_argument('--end', type=str, action='store', default=None)

    parser.add_argument('--hourly_blur', type=int, action='store', default=False)
    parser.add_argument('--daily_blur', type=int, action='store', default=False)
    parser.add_argument('--normalize', type=int, action='store', default=True)

    parser.add_argument('--show', type=bool, action='store', default=True)
    parser.add_argument('--printer_friendly', type=bool, action='store', default=False)
    parser.add_argument('--landscape', type=bool, action='store', default=True)
    parser.add_argument('--save_csv', type=bool, action='store', default=True)

    ARGS, UNK = parser.parse_known_args()

    act = main()
