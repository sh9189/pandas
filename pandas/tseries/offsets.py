from datetime import date, datetime, timedelta
from pandas.compat import range
from pandas import compat
import numpy as np

from pandas.tseries.tools import to_datetime

# import after tools, dateutil check
from dateutil.relativedelta import relativedelta, weekday
from dateutil.easter import easter
import pandas.tslib as tslib
from pandas.tslib import Timestamp, OutOfBoundsDatetime

import functools

__all__ = ['Day', 'BusinessDay', 'BDay', 'CustomBusinessDay', 'CDay',
           'CBMonthEnd','CBMonthBegin',
           'MonthBegin', 'BMonthBegin', 'MonthEnd', 'BMonthEnd',
           'YearBegin', 'BYearBegin', 'YearEnd', 'BYearEnd',
           'QuarterBegin', 'BQuarterBegin', 'QuarterEnd', 'BQuarterEnd',
           'LastWeekOfMonth', 'FY5253Quarter', 'FY5253',
           'Week', 'WeekOfMonth', 'Easter',
           'Hour', 'Minute', 'Second', 'Milli', 'Micro', 'Nano',
           'DateOffset']

# convert to/from datetime/timestamp to allow invalid Timestamp ranges to pass thru
def as_timestamp(obj):
    if isinstance(obj, Timestamp):
        return obj
    try:
        return Timestamp(obj)
    except (OutOfBoundsDatetime):
        pass
    return obj

def as_datetime(obj):
    f = getattr(obj,'to_pydatetime',None)
    if f is not None:
        obj = f()
    return obj

def apply_wraps(func):
    @functools.wraps(func)
    def wrapper(self, other):
        if other is tslib.NaT:
            return tslib.NaT
        elif isinstance(other, (timedelta, Tick, DateOffset)):
            # timedelta path
            return func(self, other)
        elif isinstance(other, (np.datetime64, datetime, date)):
            other = as_timestamp(other)

        tz = getattr(other, 'tzinfo', None)
        nano = getattr(other, 'nanosecond', 0)

        try:
            result = func(self, other)

            if self.normalize:
                # normalize_date returns normal datetime
                result = tslib.normalize_date(result)
            result = Timestamp(result)

            # nanosecond may be deleted depending on offset process
            if not self.normalize and nano != 0:
                if not isinstance(self, Nano) and result.nanosecond != nano:
                    if result.tz is not None:
                        # convert to UTC
                        value = tslib.tz_convert_single(result.value, 'UTC', result.tz)
                    else:
                        value = result.value
                    result = Timestamp(value + nano)

            if tz is not None and result.tzinfo is None:
                result = tslib._localize_pydatetime(result, tz)

        except OutOfBoundsDatetime:
            result = func(self, as_datetime(other))

            if self.normalize:
                # normalize_date returns normal datetime
                result = tslib.normalize_date(result)

            if tz is not None and result.tzinfo is None:
                result = tslib._localize_pydatetime(result, tz)

        return result
    return wrapper


def _is_normalized(dt):
    if (dt.hour != 0 or dt.minute != 0 or dt.second != 0
        or dt.microsecond != 0 or getattr(dt, 'nanosecond', 0) != 0):
        return False
    return True

#----------------------------------------------------------------------
# DateOffset


class ApplyTypeError(TypeError):
    # sentinel class for catching the apply error to return NotImplemented
    pass


class CacheableOffset(object):
    _cacheable = True


class DateOffset(object):
    """
    Standard kind of date increment used for a date range.

    Works exactly like relativedelta in terms of the keyword args you
    pass in, use of the keyword n is discouraged-- you would be better
    off specifying n in the keywords you use, but regardless it is
    there for you. n is needed for DateOffset subclasses.

    DateOffets work as follows.  Each offset specify a set of dates
    that conform to the DateOffset.  For example, Bday defines this
    set to be the set of dates that are weekdays (M-F).  To test if a
    date is in the set of a DateOffset dateOffset we can use the
    onOffset method: dateOffset.onOffset(date).

    If a date is not on a valid date, the rollback and rollforward
    methods can be used to roll the date to the nearest valid date
    before/after the date.

    DateOffsets can be created to move dates forward a given number of
    valid dates.  For example, Bday(2) can be added to a date to move
    it two business days forward.  If the date does not start on a
    valid date, first it is moved to a valid date.  Thus psedo code
    is:

    def __add__(date):
      date = rollback(date) # does nothing if date is valid
      return date + <n number of periods>

    When a date offset is created for a negitive number of periods,
    the date is first rolled forward.  The pseudo code is:

    def __add__(date):
      date = rollforward(date) # does nothing is date is valid
      return date + <n number of periods>

    Zero presents a problem.  Should it roll forward or back?  We
    arbitrarily have it rollforward:

    date + BDay(0) == BDay.rollforward(date)

    Since 0 is a bit weird, we suggest avoiding its use.
    """
    _cacheable = False
    _normalize_cache = True
    _kwds_use_relativedelta = (
        'years', 'months', 'weeks', 'days',
        'year', 'month', 'week', 'day', 'weekday',
        'hour', 'minute', 'second', 'microsecond'
        )
    _use_relativedelta = False

    # default for prior pickles
    normalize = False

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = int(n)
        self.normalize = normalize
        self.kwds = kwds
        self._offset, self._use_relativedelta = self._determine_offset()

    def _determine_offset(self):
        # timedelta is used for sub-daily plural offsets and all singular offsets
        # relativedelta is used for plural offsets of daily length or more
        # nanosecond(s) are handled by apply_wraps
        kwds_no_nanos = dict(
            (k, v) for k, v in self.kwds.items()
            if k not in ('nanosecond', 'nanoseconds')
            )
        use_relativedelta = False

        if len(kwds_no_nanos) > 0:
            if any(k in self._kwds_use_relativedelta for k in kwds_no_nanos):
                use_relativedelta = True
                offset = relativedelta(**kwds_no_nanos)
            else:
                # sub-daily offset - use timedelta (tz-aware)
                offset = timedelta(**kwds_no_nanos)
        else:
            offset = timedelta(1)
        return offset, use_relativedelta

    @apply_wraps
    def apply(self, other):
        if self._use_relativedelta:
            other = as_datetime(other)

        if len(self.kwds) > 0:
            tzinfo = getattr(other, 'tzinfo', None)
            if tzinfo is not None and self._use_relativedelta:
                # perform calculation in UTC
                other = other.replace(tzinfo=None)

            if self.n > 0:
                for i in range(self.n):
                    other = other + self._offset
            else:
                for i in range(-self.n):
                    other = other - self._offset

            if tzinfo is not None and self._use_relativedelta:
                # bring tz back from UTC calculation
                other = tslib._localize_pydatetime(other, tzinfo)

            return as_timestamp(other)
        else:
            return other + timedelta(self.n)

    def isAnchored(self):
        return (self.n == 1)

    def copy(self):
        return self.__class__(self.n, normalize=self.normalize, **self.kwds)

    def _should_cache(self):
        return self.isAnchored() and self._cacheable

    def _params(self):
        attrs = [(k, v) for k, v in compat.iteritems(vars(self))
                 if (k not in ['kwds', 'name', 'normalize',
                 'busdaycalendar']) and (k[0] != '_')]
        attrs.extend(list(self.kwds.items()))
        attrs = sorted(set(attrs))

        params = tuple([str(self.__class__)] + attrs)
        return params

    def __repr__(self):
        if hasattr(self, '_named'):
            return self._named
        className = getattr(self, '_outputName', type(self).__name__)
        exclude = set(['n', 'inc', 'normalize'])
        attrs = []
        for attr in sorted(self.__dict__):
            if ((attr == 'kwds' and len(self.kwds) == 0)
                    or attr.startswith('_')):
                continue
            elif attr == 'kwds':
                kwds_new = {}
                for key in self.kwds:
                    if not hasattr(self, key):
                        kwds_new[key] = self.kwds[key]
                if len(kwds_new) > 0:
                    attrs.append('='.join((attr, repr(kwds_new))))
            else:
                if attr not in exclude:
                    attrs.append('='.join((attr, repr(getattr(self, attr)))))

        if abs(self.n) != 1:
            plural = 's'
        else:
            plural = ''

        n_str = ""
        if self.n != 1:
            n_str = "%s * " % self.n

        out = '<%s' % n_str + className + plural
        if attrs:
            out += ': ' + ', '.join(attrs)
        out += '>'
        return out

    @property
    def name(self):
        if hasattr(self, '_named'):
            return self._named
        else:
            return self.rule_code

    def __eq__(self, other):
        if other is None:
            return False

        if isinstance(other, compat.string_types):
            from pandas.tseries.frequencies import to_offset

            other = to_offset(other)

        if not isinstance(other, DateOffset):
            return False

        return self._params() == other._params()

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self._params())

    def __call__(self, other):
        return self.apply(other)

    def __add__(self, other):
        try:
            return self.apply(other)
        except ApplyTypeError:
            return NotImplemented

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        if isinstance(other, datetime):
            raise TypeError('Cannot subtract datetime from offset.')
        elif type(other) == type(self):
            return self.__class__(self.n - other.n, normalize=self.normalize, **self.kwds)
        else:  # pragma: no cover
            return NotImplemented

    def __rsub__(self, other):
        return self.__class__(-self.n, normalize=self.normalize, **self.kwds) + other

    def __mul__(self, someInt):
        return self.__class__(n=someInt * self.n, normalize=self.normalize, **self.kwds)

    def __rmul__(self, someInt):
        return self.__mul__(someInt)

    def __neg__(self):
        return self.__class__(-self.n, normalize=self.normalize, **self.kwds)

    def rollback(self, dt):
        """Roll provided date backward to next offset only if not on offset"""
        dt = as_timestamp(dt)
        if not self.onOffset(dt):
            dt = dt - self.__class__(1, normalize=self.normalize, **self.kwds)
        return dt

    def rollforward(self, dt):
        """Roll provided date forward to next offset only if not on offset"""
        dt = as_timestamp(dt)
        if not self.onOffset(dt):
            dt = dt + self.__class__(1, normalize=self.normalize, **self.kwds)
        return dt

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        # XXX, see #1395
        if type(self) == DateOffset or isinstance(self, Tick):
            return True

        # Default (slow) method for determining if some date is a member of the
        # date range generated by this offset. Subclasses may have this
        # re-implemented in a nicer way.
        a = dt
        b = ((dt + self) - self)
        return a == b

    # way to get around weirdness with rule_code
    @property
    def _prefix(self):
        raise NotImplementedError('Prefix not defined')

    @property
    def rule_code(self):
        return self._prefix

    @property
    def freqstr(self):
        try:
            code = self.rule_code
        except NotImplementedError:
            return repr(self)

        if self.n != 1:
            fstr = '%d%s' % (self.n, code)
        else:
            fstr = code

        return fstr


class SingleConstructorOffset(DateOffset):
    @classmethod
    def _from_name(cls, suffix=None):
        # default _from_name calls cls with no args
        if suffix:
            raise ValueError("Bad freq suffix %s" % suffix)
        return cls()


class BusinessMixin(object):
    """ mixin to business types to provide related functions """

    # TODO: Combine this with DateOffset by defining a whitelisted set of
    # attributes on each object rather than the existing behavior of iterating
    # over internal ``__dict__``
    def __repr__(self):
        if hasattr(self, '_named'):
            return self._named
        className = getattr(self, '_outputName', self.__class__.__name__)
        attrs = []

        if self.offset:
            attrs = ['offset=%s' % repr(self.offset)]

        if abs(self.n) != 1:
            plural = 's'
        else:
            plural = ''

        n_str = ""
        if self.n != 1:
            n_str = "%s * " % self.n

        out = '<%s' % n_str + className + plural
        if attrs:
            out += ': ' + ', '.join(attrs)
        out += '>'
        return out

class BusinessDay(BusinessMixin, SingleConstructorOffset):
    """
    DateOffset subclass representing possibly n business days
    """
    _prefix = 'B'

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = int(n)
        self.normalize = normalize
        self.kwds = kwds
        self.offset = kwds.get('offset', timedelta(0))

    @property
    def freqstr(self):
        try:
            code = self.rule_code
        except NotImplementedError:
            return repr(self)

        if self.n != 1:
            fstr = '%d%s' % (self.n, code)
        else:
            fstr = code

        if self.offset:
            fstr += self._offset_str()

        return fstr

    def _offset_str(self):
        def get_str(td):
            off_str = ''
            if td.days > 0:
                off_str += str(td.days) + 'D'
            if td.seconds > 0:
                s = td.seconds
                hrs = int(s / 3600)
                if hrs != 0:
                    off_str += str(hrs) + 'H'
                    s -= hrs * 3600
                mts = int(s / 60)
                if mts != 0:
                    off_str += str(mts) + 'Min'
                    s -= mts * 60
                if s != 0:
                    off_str += str(s) + 's'
            if td.microseconds > 0:
                off_str += str(td.microseconds) + 'us'
            return off_str

        if isinstance(self.offset, timedelta):
            zero = timedelta(0, 0, 0)
            if self.offset >= zero:
                off_str = '+' + get_str(self.offset)
            else:
                off_str = '-' + get_str(-self.offset)
            return off_str
        else:
            return '+' + repr(self.offset)

    def isAnchored(self):
        return (self.n == 1)

    @apply_wraps
    def apply(self, other):
        if isinstance(other, datetime):
            n = self.n

            if n == 0 and other.weekday() > 4:
                n = 1

            result = other

            # avoid slowness below
            if abs(n) > 5:
                k = n // 5
                result = result + timedelta(7 * k)
                if n < 0 and result.weekday() > 4:
                    n += 1
                n -= 5 * k
                if n == 0 and result.weekday() > 4:
                    n -= 1

            while n != 0:
                k = n // abs(n)
                result = result + timedelta(k)
                if result.weekday() < 5:
                    n -= k

            if self.offset:
                result = result + self.offset
            return result

        elif isinstance(other, (timedelta, Tick)):
            return BDay(self.n, offset=self.offset + other,
                        normalize=self.normalize)
        else:
            raise ApplyTypeError('Only know how to combine business day with '
                                 'datetime or timedelta.')

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        return dt.weekday() < 5


class CustomBusinessDay(BusinessDay):
    """
    **EXPERIMENTAL** DateOffset subclass representing possibly n business days
    excluding holidays

    .. warning:: EXPERIMENTAL

        This class is not officially supported and the API is likely to change
        in future versions. Use this at your own risk.

    Parameters
    ----------
    n : int, default 1
    offset : timedelta, default timedelta(0)
    normalize : bool, default False
        Normalize start/end dates to midnight before generating date range
    weekmask : str, Default 'Mon Tue Wed Thu Fri'
        weekmask of valid business days, passed to ``numpy.busdaycalendar``
    holidays : list
        list/array of dates to exclude from the set of valid business days,
        passed to ``numpy.busdaycalendar``
    calendar : HolidayCalendar instance
        instance of AbstractHolidayCalendar that provide the list of holidays
    """

    _cacheable = False
    _prefix = 'C'

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = int(n)
        self.normalize = normalize
        self.kwds = kwds
        self.offset = kwds.get('offset', timedelta(0))
        self.weekmask = kwds.get('weekmask', 'Mon Tue Wed Thu Fri')
        
        if 'calendar' in kwds:
            holidays = kwds['calendar'].holidays()
        else:
            holidays = kwds.get('holidays', [])
        holidays = [self._to_dt64(dt, dtype='datetime64[D]') for dt in
                    holidays]
        self.holidays = tuple(sorted(holidays))
        self.kwds['holidays'] = self.holidays

        self._set_busdaycalendar()

    def _set_busdaycalendar(self):
        if self.holidays:
            kwargs = {'weekmask':self.weekmask,'holidays':self.holidays}
        else:
            kwargs = {'weekmask':self.weekmask}
        try:
            self.busdaycalendar = np.busdaycalendar(**kwargs)
        except:
            # Check we have the required numpy version
            from distutils.version import LooseVersion

            if LooseVersion(np.__version__) < '1.7.0':
                raise NotImplementedError("CustomBusinessDay requires numpy >= "
                                          "1.7.0. Current version: " +
                                          np.__version__)
            else:
                raise

    def __getstate__(self):
        """Return a pickleable state"""
        state = self.__dict__.copy()
        del state['busdaycalendar']
        return state

    def __setstate__(self, state):
        """Reconstruct an instance from a pickled state"""
        self.__dict__ = state
        self._set_busdaycalendar()

    @apply_wraps
    def apply(self, other):
        if self.n <= 0:
            roll = 'forward'
        else:
            roll = 'backward'

        if isinstance(other, datetime):
            date_in = other
            np_dt = np.datetime64(date_in.date())

            np_incr_dt = np.busday_offset(np_dt, self.n, roll=roll,
                                  busdaycal=self.busdaycalendar)

            dt_date = np_incr_dt.astype(datetime)
            result = datetime.combine(dt_date, date_in.time())

            if self.offset:
                result = result + self.offset
            return result

        elif isinstance(other, (timedelta, Tick)):
            return BDay(self.n, offset=self.offset + other,
                        normalize=self.normalize)
        else:
            raise ApplyTypeError('Only know how to combine trading day with '
                                 'datetime, datetime64 or timedelta.')

    @staticmethod
    def _to_dt64(dt, dtype='datetime64'):
        # Currently
        # > np.datetime64(dt.datetime(2013,5,1),dtype='datetime64[D]')
        # numpy.datetime64('2013-05-01T02:00:00.000000+0200')
        # Thus astype is needed to cast datetime to datetime64[D]

        if getattr(dt, 'tzinfo', None) is not None:
            i8 = tslib.pydt_to_i8(dt)
            dt = tslib.tz_convert_single(i8, 'UTC', dt.tzinfo)
            dt = Timestamp(dt)
        dt = np.datetime64(dt)
        if dt.dtype.name != dtype:
            dt = dt.astype(dtype)
        return dt

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        day64 = self._to_dt64(dt,'datetime64[D]')
        return np.is_busday(day64, busdaycal=self.busdaycalendar)


class MonthOffset(SingleConstructorOffset):
    @property
    def name(self):
        if self.isAnchored:
            return self.rule_code
        else:
            return "%s-%s" % (self.rule_code, _int_to_month[self.n])


class MonthEnd(MonthOffset):
    """DateOffset of one month end"""

    @apply_wraps
    def apply(self, other):
        n = self.n
        _, days_in_month = tslib.monthrange(other.year, other.month)
        if other.day != days_in_month:
            other = other + relativedelta(months=-1, day=31)
            if n <= 0:
                n = n + 1
        other = other + relativedelta(months=n, day=31)
        return other

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        days_in_month = tslib.monthrange(dt.year, dt.month)[1]
        return dt.day == days_in_month

    _prefix = 'M'


class MonthBegin(MonthOffset):
    """DateOffset of one month at beginning"""

    @apply_wraps
    def apply(self, other):
        n = self.n

        if other.day > 1 and n <= 0:  # then roll forward if n<=0
            n += 1

        return other + relativedelta(months=n, day=1)

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        return dt.day == 1

    _prefix = 'MS'


class BusinessMonthEnd(MonthOffset):
    """DateOffset increments between business EOM dates"""

    def isAnchored(self):
        return (self.n == 1)

    @apply_wraps
    def apply(self, other):
        n = self.n
        wkday, days_in_month = tslib.monthrange(other.year, other.month)
        lastBDay = days_in_month - max(((wkday + days_in_month - 1)
                                        % 7) - 4, 0)

        if n > 0 and not other.day >= lastBDay:
            n = n - 1
        elif n <= 0 and other.day > lastBDay:
            n = n + 1
        other = other + relativedelta(months=n, day=31)

        if other.weekday() > 4:
            other = other - BDay()
        return other

    _prefix = 'BM'


class BusinessMonthBegin(MonthOffset):
    """DateOffset of one business month at beginning"""

    @apply_wraps
    def apply(self, other):
        n = self.n
        wkday, _ = tslib.monthrange(other.year, other.month)
        first = _get_firstbday(wkday)

        if other.day > first and n <= 0:
            # as if rolled forward already
            n += 1
        elif other.day < first and n > 0:
            other = other + timedelta(days=first - other.day)
            n -= 1

        other = other + relativedelta(months=n)
        wkday, _ = tslib.monthrange(other.year, other.month)
        first = _get_firstbday(wkday)
        result = datetime(other.year, other.month, first, other.hour, other.minute,
                          other.second, other.microsecond)
        return result

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        first_weekday, _ = tslib.monthrange(dt.year, dt.month)
        if first_weekday == 5:
            return dt.day == 3
        elif first_weekday == 6:
            return dt.day == 2
        else:
            return dt.day == 1

    _prefix = 'BMS'



class CustomBusinessMonthEnd(BusinessMixin, MonthOffset):
    """
    **EXPERIMENTAL** DateOffset of one custom business month

    .. warning:: EXPERIMENTAL

        This class is not officially supported and the API is likely to change
        in future versions. Use this at your own risk.

    Parameters
    ----------
    n : int, default 1
    offset : timedelta, default timedelta(0)
    normalize : bool, default False
        Normalize start/end dates to midnight before generating date range
    weekmask : str, Default 'Mon Tue Wed Thu Fri'
        weekmask of valid business days, passed to ``numpy.busdaycalendar``
    holidays : list
        list/array of dates to exclude from the set of valid business days,
        passed to ``numpy.busdaycalendar``
    """

    _cacheable = False
    _prefix = 'CBM'
    def __init__(self, n=1, normalize=False, **kwds):
        self.n = int(n)
        self.normalize = normalize
        self.kwds = kwds
        self.offset = kwds.get('offset', timedelta(0))
        self.weekmask = kwds.get('weekmask', 'Mon Tue Wed Thu Fri')
        self.cbday = CustomBusinessDay(n=self.n, **kwds)
        self.m_offset = MonthEnd()

    @apply_wraps
    def apply(self,other):
        n = self.n
        # First move to month offset
        cur_mend = self.m_offset.rollforward(other)
        # Find this custom month offset
        cur_cmend = self.cbday.rollback(cur_mend)

        # handle zero case. arbitrarily rollforward
        if n == 0 and other != cur_cmend:
            n += 1

        if other < cur_cmend and n >= 1:
            n -= 1
        elif other > cur_cmend and n <= -1:
            n += 1
 
        new = cur_mend + n * MonthEnd()
        result = self.cbday.rollback(new)
        return result
        
class CustomBusinessMonthBegin(BusinessMixin, MonthOffset):
    """
    **EXPERIMENTAL** DateOffset of one custom business month

    .. warning:: EXPERIMENTAL

        This class is not officially supported and the API is likely to change
        in future versions. Use this at your own risk.

    Parameters
    ----------
    n : int, default 1
    offset : timedelta, default timedelta(0)
    normalize : bool, default False
        Normalize start/end dates to midnight before generating date range
    weekmask : str, Default 'Mon Tue Wed Thu Fri'
        weekmask of valid business days, passed to ``numpy.busdaycalendar``
    holidays : list
        list/array of dates to exclude from the set of valid business days,
        passed to ``numpy.busdaycalendar``
    """

    _cacheable = False
    _prefix = 'CBMS'
    def __init__(self, n=1, normalize=False, **kwds):
        self.n = int(n)
        self.normalize = normalize
        self.kwds = kwds
        self.offset = kwds.get('offset', timedelta(0))
        self.weekmask = kwds.get('weekmask', 'Mon Tue Wed Thu Fri')
        self.cbday = CustomBusinessDay(n=self.n, normalize=normalize, **kwds)
        self.m_offset = MonthBegin(normalize=normalize)

    @apply_wraps
    def apply(self,other):
        n = self.n
        dt_in = other
        # First move to month offset
        cur_mbegin = self.m_offset.rollback(dt_in)
        # Find this custom month offset
        cur_cmbegin = self.cbday.rollforward(cur_mbegin)

        # handle zero case. arbitrarily rollforward
        if n == 0 and dt_in != cur_cmbegin:
            n += 1

        if dt_in > cur_cmbegin and n <= -1:
            n += 1
        elif dt_in < cur_cmbegin and n >= 1:
            n -= 1
 
        new = cur_mbegin + n * MonthBegin()
        result = self.cbday.rollforward(new)
        return result

class Week(DateOffset):
    """
    Weekly offset

    Parameters
    ----------
    weekday : int, default None
        Always generate specific day of week. 0 for Monday
    """

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize
        self.weekday = kwds.get('weekday', None)

        if self.weekday is not None:
            if self.weekday < 0 or self.weekday > 6:
                raise ValueError('Day must be 0<=day<=6, got %d' %
                                 self.weekday)

        self._inc = timedelta(weeks=1)
        self.kwds = kwds

    def isAnchored(self):
        return (self.n == 1 and self.weekday is not None)

    @apply_wraps
    def apply(self, other):
        base = other
        if self.weekday is None:
            return other + self.n * self._inc

        if self.n > 0:
            k = self.n
            otherDay = other.weekday()
            if otherDay != self.weekday:
                other = other + timedelta((self.weekday - otherDay) % 7)
                k = k - 1
            other = other
            for i in range(k):
                other = other + self._inc
        else:
            k = self.n
            otherDay = other.weekday()
            if otherDay != self.weekday:
                other = other + timedelta((self.weekday - otherDay) % 7)
            for i in range(-k):
                other = other - self._inc

        other = datetime(other.year, other.month, other.day,
                         base.hour, base.minute, base.second, base.microsecond)
        return other

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        return dt.weekday() == self.weekday

    _prefix = 'W'

    @property
    def rule_code(self):
        suffix = ''
        if self.weekday is not None:
            suffix = '-%s' % (_int_to_weekday[self.weekday])
        return self._prefix + suffix

    @classmethod
    def _from_name(cls, suffix=None):
        if not suffix:
            weekday = None
        else:
            weekday = _weekday_to_int[suffix]
        return cls(weekday=weekday)

class WeekDay(object):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6

_int_to_weekday = {
    WeekDay.MON: 'MON',
    WeekDay.TUE: 'TUE',
    WeekDay.WED: 'WED',
    WeekDay.THU: 'THU',
    WeekDay.FRI: 'FRI',
    WeekDay.SAT: 'SAT',
    WeekDay.SUN: 'SUN'
}

_weekday_to_int = dict((v, k) for k, v in _int_to_weekday.items())


class WeekOfMonth(DateOffset):
    """
    Describes monthly dates like "the Tuesday of the 2nd week of each month"

    Parameters
    ----------
    n : int
    week : {0, 1, 2, 3, ...}
        0 is 1st week of month, 1 2nd week, etc.
    weekday : {0, 1, ..., 6}
        0: Mondays
        1: Tuesdays
        2: Wednesdays
        3: Thursdays
        4: Fridays
        5: Saturdays
        6: Sundays
    """

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize
        self.weekday = kwds['weekday']
        self.week = kwds['week']

        if self.n == 0:
            raise ValueError('N cannot be 0')

        if self.weekday < 0 or self.weekday > 6:
            raise ValueError('Day must be 0<=day<=6, got %d' %
                             self.weekday)
        if self.week < 0 or self.week > 3:
            raise ValueError('Week must be 0<=day<=3, got %d' %
                             self.week)

        self.kwds = kwds

    @apply_wraps
    def apply(self, other):
        base = other
        offsetOfMonth = self.getOffsetOfMonth(other)

        if offsetOfMonth > other:
            if self.n > 0:
                months = self.n - 1
            else:
                months = self.n
        elif offsetOfMonth == other:
            months = self.n
        else:
            if self.n > 0:
                months = self.n
            else:
                months = self.n + 1

        other = self.getOffsetOfMonth(other + relativedelta(months=months, day=1))
        other = datetime(other.year, other.month, other.day, base.hour,
                         base.minute, base.second, base.microsecond)
        return other

    def getOffsetOfMonth(self, dt):
        w = Week(weekday=self.weekday)
        d = datetime(dt.year, dt.month, 1, tzinfo=dt.tzinfo)
        d = w.rollforward(d)

        for i in range(self.week):
            d = w.apply(d)

        return d

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        d = datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo)
        return d == self.getOffsetOfMonth(dt)

    @property
    def rule_code(self):
        return '%s-%d%s' % (self._prefix, self.week + 1,
                            _int_to_weekday.get(self.weekday, ''))

    _prefix = 'WOM'

    @classmethod
    def _from_name(cls, suffix=None):
        if not suffix:
            raise ValueError("Prefix %r requires a suffix." % (cls._prefix))
        # TODO: handle n here...
        # only one digit weeks (1 --> week 0, 2 --> week 1, etc.)
        week = int(suffix[0]) - 1
        weekday = _weekday_to_int[suffix[1:]]
        return cls(week=week, weekday=weekday)

class LastWeekOfMonth(DateOffset):
    """
    Describes monthly dates in last week of month like "the last Tuesday of each month"

    Parameters
    ----------
    n : int
    weekday : {0, 1, ..., 6}
        0: Mondays
        1: Tuesdays
        2: Wednesdays
        3: Thursdays
        4: Fridays
        5: Saturdays
        6: Sundays
    """
    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize
        self.weekday = kwds['weekday']

        if self.n == 0:
            raise ValueError('N cannot be 0')

        if self.weekday < 0 or self.weekday > 6:
            raise ValueError('Day must be 0<=day<=6, got %d' %
                            self.weekday)

        self.kwds = kwds

    @apply_wraps
    def apply(self, other):
        offsetOfMonth = self.getOffsetOfMonth(other)

        if offsetOfMonth > other:
            if self.n > 0:
                months = self.n - 1
            else:
                months = self.n
        elif offsetOfMonth == other:
            months = self.n
        else:
            if self.n > 0:
                months = self.n
            else:
                months = self.n + 1

        return self.getOffsetOfMonth(other + relativedelta(months=months, day=1))

    def getOffsetOfMonth(self, dt):
        m =  MonthEnd()
        d = datetime(dt.year, dt.month, 1, dt.hour, dt.minute,
                     dt.second, dt.microsecond, tzinfo=dt.tzinfo)
        eom = m.rollforward(d)
        w = Week(weekday=self.weekday)
        return w.rollback(eom)

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        return dt == self.getOffsetOfMonth(dt)

    @property
    def rule_code(self):
        return '%s-%s' % (self._prefix, _int_to_weekday.get(self.weekday, ''))

    _prefix = 'LWOM'

    @classmethod
    def _from_name(cls, suffix=None):
        if not suffix:
            raise ValueError("Prefix %r requires a suffix." % (cls._prefix))
        # TODO: handle n here...
        weekday = _weekday_to_int[suffix]
        return cls(weekday=weekday)


class QuarterOffset(DateOffset):
    """Quarter representation - doesn't call super"""

    #: default month for __init__
    _default_startingMonth = None
    #: default month in _from_name
    _from_name_startingMonth = None

    # TODO: Consider combining QuarterOffset and YearOffset __init__ at some
    #       point
    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize
        self.startingMonth = kwds.get('startingMonth',
                                      self._default_startingMonth)

        self.kwds = kwds

    def isAnchored(self):
        return (self.n == 1 and self.startingMonth is not None)

    @classmethod
    def _from_name(cls, suffix=None):
        kwargs = {}
        if suffix:
            kwargs['startingMonth'] = _month_to_int[suffix]
        else:
            if cls._from_name_startingMonth is not None:
                kwargs['startingMonth'] = cls._from_name_startingMonth
        return cls(**kwargs)

    @property
    def rule_code(self):
        return '%s-%s' % (self._prefix, _int_to_month[self.startingMonth])


class BQuarterEnd(QuarterOffset):
    """DateOffset increments between business Quarter dates
    startingMonth = 1 corresponds to dates like 1/31/2007, 4/30/2007, ...
    startingMonth = 2 corresponds to dates like 2/28/2007, 5/31/2007, ...
    startingMonth = 3 corresponds to dates like 3/30/2007, 6/29/2007, ...
    """
    _outputName = 'BusinessQuarterEnd'
    _default_startingMonth = 3
    # 'BQ'
    _from_name_startingMonth = 12
    _prefix = 'BQ'

    @apply_wraps
    def apply(self, other):
        n = self.n
        base = other
        other = datetime(other.year, other.month, other.day,
                         other.hour, other.minute, other.second,
                         other.microsecond)

        wkday, days_in_month = tslib.monthrange(other.year, other.month)
        lastBDay = days_in_month - max(((wkday + days_in_month - 1)
                                        % 7) - 4, 0)

        monthsToGo = 3 - ((other.month - self.startingMonth) % 3)
        if monthsToGo == 3:
            monthsToGo = 0

        if n > 0 and not (other.day >= lastBDay and monthsToGo == 0):
            n = n - 1
        elif n <= 0 and other.day > lastBDay and monthsToGo == 0:
            n = n + 1

        other = other + relativedelta(months=monthsToGo + 3 * n, day=31)
        other = tslib._localize_pydatetime(other, base.tzinfo)
        if other.weekday() > 4:
            other = other - BDay()
        return other

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        modMonth = (dt.month - self.startingMonth) % 3
        return BMonthEnd().onOffset(dt) and modMonth == 0


_int_to_month = {
    1: 'JAN',
    2: 'FEB',
    3: 'MAR',
    4: 'APR',
    5: 'MAY',
    6: 'JUN',
    7: 'JUL',
    8: 'AUG',
    9: 'SEP',
    10: 'OCT',
    11: 'NOV',
    12: 'DEC'
}

_month_to_int = dict((v, k) for k, v in _int_to_month.items())


# TODO: This is basically the same as BQuarterEnd
class BQuarterBegin(QuarterOffset):
    _outputName = "BusinessQuarterBegin"
    # I suspect this is wrong for *all* of them.
    _default_startingMonth = 3
    _from_name_startingMonth = 1
    _prefix = 'BQS'

    @apply_wraps
    def apply(self, other):
        n = self.n
        wkday, _ = tslib.monthrange(other.year, other.month)

        first = _get_firstbday(wkday)

        monthsSince = (other.month - self.startingMonth) % 3

        if n <= 0 and monthsSince != 0:  # make sure to roll forward so negate
            monthsSince = monthsSince - 3

        # roll forward if on same month later than first bday
        if n <= 0 and (monthsSince == 0 and other.day > first):
            n = n + 1
        # pretend to roll back if on same month but before firstbday
        elif n > 0 and (monthsSince == 0 and other.day < first):
            n = n - 1

        # get the first bday for result
        other = other + relativedelta(months=3 * n - monthsSince)
        wkday, _ = tslib.monthrange(other.year, other.month)
        first = _get_firstbday(wkday)
        result = datetime(other.year, other.month, first,
                          other.hour, other.minute, other.second,
                          other.microsecond)
        return result


class QuarterEnd(QuarterOffset):
    """DateOffset increments between business Quarter dates
    startingMonth = 1 corresponds to dates like 1/31/2007, 4/30/2007, ...
    startingMonth = 2 corresponds to dates like 2/28/2007, 5/31/2007, ...
    startingMonth = 3 corresponds to dates like 3/31/2007, 6/30/2007, ...
    """
    _outputName = 'QuarterEnd'
    _default_startingMonth = 3
    _prefix = 'Q'

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize
        self.startingMonth = kwds.get('startingMonth', 3)

        self.kwds = kwds

    def isAnchored(self):
        return (self.n == 1 and self.startingMonth is not None)

    @apply_wraps
    def apply(self, other):
        n = self.n
        other = datetime(other.year, other.month, other.day,
                         other.hour, other.minute, other.second,
                         other.microsecond)
        wkday, days_in_month = tslib.monthrange(other.year, other.month)

        monthsToGo = 3 - ((other.month - self.startingMonth) % 3)
        if monthsToGo == 3:
            monthsToGo = 0

        if n > 0 and not (other.day >= days_in_month and monthsToGo == 0):
            n = n - 1

        other = other + relativedelta(months=monthsToGo + 3 * n, day=31)
        return other

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        modMonth = (dt.month - self.startingMonth) % 3
        return MonthEnd().onOffset(dt) and modMonth == 0


class QuarterBegin(QuarterOffset):
    _outputName = 'QuarterBegin'
    _default_startingMonth = 3
    _from_name_startingMonth = 1
    _prefix = 'QS'

    def isAnchored(self):
        return (self.n == 1 and self.startingMonth is not None)

    @apply_wraps
    def apply(self, other):
        n = self.n
        wkday, days_in_month = tslib.monthrange(other.year, other.month)

        monthsSince = (other.month - self.startingMonth) % 3

        if n <= 0 and monthsSince != 0:
            # make sure you roll forward, so negate
            monthsSince = monthsSince - 3

        if n < 0 and (monthsSince == 0 and other.day > 1):
            # after start, so come back an extra period as if rolled forward
            n = n + 1

        other = other + relativedelta(months=3 * n - monthsSince, day=1)
        return other


class YearOffset(DateOffset):
    """DateOffset that just needs a month"""

    def __init__(self, n=1, normalize=False, **kwds):
        self.month = kwds.get('month', self._default_month)

        if self.month < 1 or self.month > 12:
            raise ValueError('Month must go from 1 to 12')

        DateOffset.__init__(self, n=n, normalize=normalize, **kwds)

    @classmethod
    def _from_name(cls, suffix=None):
        kwargs = {}
        if suffix:
            kwargs['month'] = _month_to_int[suffix]
        return cls(**kwargs)

    @property
    def rule_code(self):
        return '%s-%s' % (self._prefix, _int_to_month[self.month])


class BYearEnd(YearOffset):
    """DateOffset increments between business EOM dates"""
    _outputName = 'BusinessYearEnd'
    _default_month = 12
    _prefix = 'BA'

    @apply_wraps
    def apply(self, other):
        n = self.n
        wkday, days_in_month = tslib.monthrange(other.year, self.month)
        lastBDay = (days_in_month -
                    max(((wkday + days_in_month - 1) % 7) - 4, 0))

        years = n
        if n > 0:
            if (other.month < self.month or
                    (other.month == self.month and other.day < lastBDay)):
                years -= 1
        elif n <= 0:
            if (other.month > self.month or
                    (other.month == self.month and other.day > lastBDay)):
                years += 1

        other = other + relativedelta(years=years)

        _, days_in_month = tslib.monthrange(other.year, self.month)
        result = datetime(other.year, self.month, days_in_month,
                          other.hour, other.minute, other.second,
                          other.microsecond)

        if result.weekday() > 4:
            result = result - BDay()

        return result


class BYearBegin(YearOffset):
    """DateOffset increments between business year begin dates"""
    _outputName = 'BusinessYearBegin'
    _default_month = 1
    _prefix = 'BAS'

    @apply_wraps
    def apply(self, other):
        n = self.n
        wkday, days_in_month = tslib.monthrange(other.year, self.month)

        first = _get_firstbday(wkday)

        years = n

        if n > 0:  # roll back first for positive n
            if (other.month < self.month or
                    (other.month == self.month and other.day < first)):
                years -= 1
        elif n <= 0:  # roll forward
            if (other.month > self.month or
                    (other.month == self.month and other.day > first)):
                years += 1

        # set first bday for result
        other = other + relativedelta(years=years)
        wkday, days_in_month = tslib.monthrange(other.year, self.month)
        first = _get_firstbday(wkday)
        return datetime(other.year, self.month, first, other.hour,
                        other.minute, other.second, other.microsecond)


class YearEnd(YearOffset):
    """DateOffset increments between calendar year ends"""
    _default_month = 12
    _prefix = 'A'

    @apply_wraps
    def apply(self, other):
        def _increment(date):
            if date.month == self.month:
                _, days_in_month = tslib.monthrange(date.year, self.month)
                if date.day != days_in_month:
                    year = date.year
                else:
                    year = date.year + 1
            elif date.month < self.month:
                year = date.year
            else:
                year = date.year + 1
            _, days_in_month = tslib.monthrange(year, self.month)
            return datetime(year, self.month, days_in_month,
                            date.hour, date.minute, date.second,
                            date.microsecond)

        def _decrement(date):
            year = date.year if date.month > self.month else date.year - 1
            _, days_in_month = tslib.monthrange(year, self.month)
            return datetime(year, self.month, days_in_month,
                            date.hour, date.minute, date.second,
                            date.microsecond)

        def _rollf(date):
            if date.month != self.month or\
               date.day < tslib.monthrange(date.year, date.month)[1]:
                date = _increment(date)
            return date

        n = self.n
        result = other
        if n > 0:
            while n > 0:
                result = _increment(result)
                n -= 1
        elif n < 0:
            while n < 0:
                result = _decrement(result)
                n += 1
        else:
            # n == 0, roll forward
            result = _rollf(result)
        return result

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        wkday, days_in_month = tslib.monthrange(dt.year, self.month)
        return self.month == dt.month and dt.day == days_in_month


class YearBegin(YearOffset):
    """DateOffset increments between calendar year begin dates"""
    _default_month = 1
    _prefix = 'AS'

    @apply_wraps
    def apply(self, other):
        def _increment(date, n):
            year = date.year + n - 1
            if date.month >= self.month:
                year += 1
            return datetime(year, self.month, 1, date.hour, date.minute,
                            date.second, date.microsecond)

        def _decrement(date, n):
            year = date.year + n + 1
            if date.month < self.month or (date.month == self.month and
                                           date.day == 1):
                year -= 1
            return datetime(year, self.month, 1, date.hour, date.minute,
                            date.second, date.microsecond)

        def _rollf(date):
            if (date.month != self.month) or date.day > 1:
                date = _increment(date, 1)
            return date

        n = self.n
        result = other
        if n > 0:
            result = _increment(result, n)
        elif n < 0:
            result = _decrement(result, n)
        else:
            # n == 0, roll forward
            result = _rollf(result)
        return result

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        return dt.month == self.month and dt.day == 1


class FY5253(DateOffset):
    """
    Describes 52-53 week fiscal year. This is also known as a 4-4-5 calendar.

    It is used by companies that desire that their
    fiscal year always end on the same day of the week.

    It is a method of managing accounting periods.
    It is a common calendar structure for some industries,
    such as retail, manufacturing and parking industry.

    For more information see:
    http://en.wikipedia.org/wiki/4%E2%80%934%E2%80%935_calendar


    The year may either:
    - end on the last X day of the Y month.
    - end on the last X day closest to the last day of the Y month.

    X is a specific day of the week.
    Y is a certain month of the year

    Parameters
    ----------
    n : int
    weekday : {0, 1, ..., 6}
        0: Mondays
        1: Tuesdays
        2: Wednesdays
        3: Thursdays
        4: Fridays
        5: Saturdays
        6: Sundays
    startingMonth : The month in which fiscal years end. {1, 2, ... 12}
    variation : str
        {"nearest", "last"} for "LastOfMonth" or "NearestEndMonth"
    """

    _prefix = 'RE'
    _suffix_prefix_last = 'L'
    _suffix_prefix_nearest = 'N'

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize
        self.startingMonth = kwds['startingMonth']
        self.weekday = kwds["weekday"]

        self.variation = kwds["variation"]

        self.kwds = kwds

        if self.n == 0:
            raise ValueError('N cannot be 0')

        if self.variation not in ["nearest", "last"]:
            raise ValueError('%s is not a valid variation' % self.variation)

        if self.variation == "nearest":
            weekday_offset = weekday(self.weekday)
            self._rd_forward = relativedelta(weekday=weekday_offset)
            self._rd_backward = relativedelta(weekday=weekday_offset(-1))
        else:
            self._offset_lwom = LastWeekOfMonth(n=1, weekday=self.weekday)

    def isAnchored(self):
        return self.n == 1 \
                and self.startingMonth is not None \
                and self.weekday is not None

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        dt = datetime(dt.year, dt.month, dt.day)
        year_end = self.get_year_end(dt)

        if self.variation == "nearest":
            # We have to check the year end of "this" cal year AND the previous
            return year_end == dt or \
                self.get_year_end(dt - relativedelta(months=1)) == dt
        else:
            return year_end == dt

    @apply_wraps
    def apply(self, other):
        n = self.n
        prev_year = self.get_year_end(
                        datetime(other.year - 1, self.startingMonth, 1))
        cur_year = self.get_year_end(
                        datetime(other.year, self.startingMonth, 1))
        next_year = self.get_year_end(
                        datetime(other.year + 1, self.startingMonth, 1))
        prev_year = tslib._localize_pydatetime(prev_year, other.tzinfo)
        cur_year = tslib._localize_pydatetime(cur_year, other.tzinfo)
        next_year = tslib._localize_pydatetime(next_year, other.tzinfo)

        if n > 0:
            if other == prev_year:
                year = other.year - 1
            elif other == cur_year:
                year = other.year
            elif other == next_year:
                year = other.year + 1
            elif other < prev_year:
                year = other.year - 1
                n -= 1
            elif other < cur_year:
                year = other.year
                n -= 1
            elif other < next_year:
                year = other.year + 1
                n -= 1
            else:
                assert False

            result = self.get_year_end(datetime(year + n, self.startingMonth, 1))

            result = datetime(result.year, result.month, result.day,
                              other.hour, other.minute, other.second, other.microsecond)
            return result
        else:
            n = -n
            if other == prev_year:
                year = other.year - 1
            elif other == cur_year:
                year = other.year
            elif other == next_year:
                year = other.year + 1
            elif other > next_year:
                year = other.year + 1
                n -= 1
            elif other > cur_year:
                year = other.year
                n -= 1
            elif other > prev_year:
                year = other.year - 1
                n -= 1
            else:
                assert False

            result = self.get_year_end(datetime(year - n, self.startingMonth, 1))

            result = datetime(result.year, result.month, result.day,
                              other.hour, other.minute, other.second, other.microsecond)
            return result

    def get_year_end(self, dt):
        if self.variation == "nearest":
            return self._get_year_end_nearest(dt)
        else:
            return self._get_year_end_last(dt)

    def get_target_month_end(self, dt):
        target_month = datetime(dt.year, self.startingMonth, 1, tzinfo=dt.tzinfo)
        next_month_first_of = target_month + relativedelta(months=+1)
        return next_month_first_of + relativedelta(days=-1)

    def _get_year_end_nearest(self, dt):
        target_date = self.get_target_month_end(dt)
        if target_date.weekday() == self.weekday:
            return target_date
        else:
            forward = target_date + self._rd_forward
            backward = target_date + self._rd_backward

            if forward - target_date < target_date - backward:
                return forward
            else:
                return backward

    def _get_year_end_last(self, dt):
        current_year = datetime(dt.year, self.startingMonth, 1, tzinfo=dt.tzinfo)
        return current_year + self._offset_lwom

    @property
    def rule_code(self):
        suffix = self.get_rule_code_suffix()
        return "%s-%s" % (self._get_prefix(), suffix)

    def _get_prefix(self):
        return self._prefix

    def _get_suffix_prefix(self):
        if self.variation == "nearest":
            return self._suffix_prefix_nearest
        else:
            return self._suffix_prefix_last

    def get_rule_code_suffix(self):
        return '%s-%s-%s' % (self._get_suffix_prefix(), \
                           _int_to_month[self.startingMonth], \
                         _int_to_weekday[self.weekday])

    @classmethod
    def _parse_suffix(cls, varion_code, startingMonth_code, weekday_code):
        if varion_code == "N":
            variation = "nearest"
        elif varion_code == "L":
            variation = "last"
        else:
            raise ValueError(
                "Unable to parse varion_code: %s" % (varion_code,))

        startingMonth = _month_to_int[startingMonth_code]
        weekday = _weekday_to_int[weekday_code]

        return {
                "weekday": weekday,
                "startingMonth": startingMonth,
                "variation": variation,
                }

    @classmethod
    def _from_name(cls, *args):
        return cls(**cls._parse_suffix(*args))


class FY5253Quarter(DateOffset):
    """
    DateOffset increments between business quarter dates
    for 52-53 week fiscal year (also known as a 4-4-5 calendar).

    It is used by companies that desire that their
    fiscal year always end on the same day of the week.

    It is a method of managing accounting periods.
    It is a common calendar structure for some industries,
    such as retail, manufacturing and parking industry.

    For more information see:
    http://en.wikipedia.org/wiki/4%E2%80%934%E2%80%935_calendar

    The year may either:
    - end on the last X day of the Y month.
    - end on the last X day closest to the last day of the Y month.

    X is a specific day of the week.
    Y is a certain month of the year

    startingMonth = 1 corresponds to dates like 1/31/2007, 4/30/2007, ...
    startingMonth = 2 corresponds to dates like 2/28/2007, 5/31/2007, ...
    startingMonth = 3 corresponds to dates like 3/30/2007, 6/29/2007, ...

    Parameters
    ----------
    n : int
    weekday : {0, 1, ..., 6}
        0: Mondays
        1: Tuesdays
        2: Wednesdays
        3: Thursdays
        4: Fridays
        5: Saturdays
        6: Sundays
    startingMonth : The month in which fiscal years end. {1, 2, ... 12}
    qtr_with_extra_week : The quarter number that has the leap
        or 14 week when needed. {1,2,3,4}
    variation : str
        {"nearest", "last"} for "LastOfMonth" or "NearestEndMonth"
    """

    _prefix = 'REQ'

    def __init__(self, n=1, normalize=False, **kwds):
        self.n = n
        self.normalize = normalize

        self.qtr_with_extra_week = kwds["qtr_with_extra_week"]

        self.kwds = kwds

        if self.n == 0:
            raise ValueError('N cannot be 0')

        self._offset = FY5253( \
                            startingMonth=kwds['startingMonth'], \
                            weekday=kwds["weekday"],
                            variation=kwds["variation"])

    def isAnchored(self):
        return self.n == 1 and self._offset.isAnchored()

    @apply_wraps
    def apply(self, other):
        base = other
        n = self.n

        if n > 0:
            while n > 0:
                if not self._offset.onOffset(other):
                    qtr_lens = self.get_weeks(other)
                    start = other - self._offset
                else:
                    start = other
                    qtr_lens = self.get_weeks(other + self._offset)

                for weeks in qtr_lens:
                    start += relativedelta(weeks=weeks)
                    if start > other:
                        other = start
                        n -= 1
                        break

        else:
            n = -n
            while n > 0:
                if not self._offset.onOffset(other):
                    qtr_lens = self.get_weeks(other)
                    end = other + self._offset
                else:
                    end = other
                    qtr_lens = self.get_weeks(other)

                for weeks in reversed(qtr_lens):
                    end -= relativedelta(weeks=weeks)
                    if end < other:
                        other = end
                        n -= 1
                        break
        other = datetime(other.year, other.month, other.day,
                         base.hour, base.minute, base.second, base.microsecond)
        return other

    def get_weeks(self, dt):
        ret = [13] * 4

        year_has_extra_week = self.year_has_extra_week(dt)

        if year_has_extra_week:
            ret[self.qtr_with_extra_week - 1] = 14

        return ret

    def year_has_extra_week(self, dt):
        if self._offset.onOffset(dt):
            prev_year_end = dt - self._offset
            next_year_end = dt
        else:
            next_year_end = dt + self._offset
            prev_year_end = dt - self._offset

        week_in_year = (next_year_end - prev_year_end).days / 7

        return week_in_year == 53

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        if self._offset.onOffset(dt):
            return True

        next_year_end = dt - self._offset

        qtr_lens = self.get_weeks(dt)

        current = next_year_end
        for qtr_len in qtr_lens[0:4]:
            current += relativedelta(weeks=qtr_len)
            if dt == current:
                return True
        return False

    @property
    def rule_code(self):
        suffix = self._offset.get_rule_code_suffix()
        return "%s-%s" % (self._prefix,
                          "%s-%d" % (suffix, self.qtr_with_extra_week))

    @classmethod
    def _from_name(cls, *args):
        return cls(**dict(FY5253._parse_suffix(*args[:-1]),
                          qtr_with_extra_week=int(args[-1])))

class Easter(DateOffset):
    '''
    DateOffset for the Easter holiday using
    logic defined in dateutil.  Right now uses
    the revised method which is valid in years
    1583-4099.
    '''
    def __init__(self, n=1, **kwds):
        super(Easter, self).__init__(n, **kwds)

    @apply_wraps
    def apply(self, other):
        currentEaster = easter(other.year)
        currentEaster = datetime(currentEaster.year, currentEaster.month, currentEaster.day)
        currentEaster = tslib._localize_pydatetime(currentEaster, other.tzinfo)

        # NOTE: easter returns a datetime.date so we have to convert to type of other
        if self.n >= 0:
            if other >= currentEaster:
                new = easter(other.year + self.n)
            else:
                new = easter(other.year + self.n - 1)
        else:
            if other > currentEaster:
                new = easter(other.year + self.n + 1)
            else:
                new = easter(other.year + self.n)

        new = datetime(new.year, new.month, new.day, other.hour,
                       other.minute, other.second, other.microsecond)
        return new

    def onOffset(self, dt):
        if self.normalize and not _is_normalized(dt):
            return False
        return date(dt.year, dt.month, dt.day) == easter(dt.year)

#----------------------------------------------------------------------
# Ticks

import operator


def _tick_comp(op):
    def f(self, other):
        return op(self.delta, other.delta)

    return f


class Tick(SingleConstructorOffset):
    _inc = timedelta(microseconds=1000)

    __gt__ = _tick_comp(operator.gt)
    __ge__ = _tick_comp(operator.ge)
    __lt__ = _tick_comp(operator.lt)
    __le__ = _tick_comp(operator.le)
    __eq__ = _tick_comp(operator.eq)
    __ne__ = _tick_comp(operator.ne)

    def __add__(self, other):
        if isinstance(other, Tick):
            if type(self) == type(other):
                return type(self)(self.n + other.n)
            else:
                return _delta_to_tick(self.delta + other.delta)
        try:
            return self.apply(other)
        except ApplyTypeError:
            return NotImplemented

    def __eq__(self, other):
        if isinstance(other, compat.string_types):
            from pandas.tseries.frequencies import to_offset

            other = to_offset(other)

        if isinstance(other, Tick):
            return self.delta == other.delta
        else:
            return DateOffset.__eq__(self, other)

    # This is identical to DateOffset.__hash__, but has to be redefined here
    # for Python 3, because we've redefined __eq__.
    def __hash__(self):
        return hash(self._params())

    def __ne__(self, other):
        if isinstance(other, compat.string_types):
            from pandas.tseries.frequencies import to_offset

            other = to_offset(other)

        if isinstance(other, Tick):
            return self.delta != other.delta
        else:
            return DateOffset.__ne__(self, other)

    @property
    def delta(self):
        return self.n * self._inc

    @property
    def nanos(self):
        return _delta_to_nanoseconds(self.delta)

    def apply(self, other):
        # Timestamp can handle tz and nano sec, thus no need to use apply_wraps
        if isinstance(other, (datetime, np.datetime64, date)):
            return as_timestamp(other) + self
        if isinstance(other, timedelta):
            return other + self.delta
        elif isinstance(other, type(self)):
            return type(self)(self.n + other.n)
        else:
            raise ApplyTypeError('Unhandled type: %s' % type(other).__name__)

    _prefix = 'undefined'

    def isAnchored(self):
        return False


def _delta_to_tick(delta):
    if delta.microseconds == 0:
        if delta.seconds == 0:
            return Day(delta.days)
        else:
            seconds = delta.days * 86400 + delta.seconds
            if seconds % 3600 == 0:
                return Hour(seconds / 3600)
            elif seconds % 60 == 0:
                return Minute(seconds / 60)
            else:
                return Second(seconds)
    else:
        nanos = _delta_to_nanoseconds(delta)
        if nanos % 1000000 == 0:
            return Milli(nanos // 1000000)
        elif nanos % 1000 == 0:
            return Micro(nanos // 1000)
        else:  # pragma: no cover
            return Nano(nanos)

_delta_to_nanoseconds = tslib._delta_to_nanoseconds


class Day(Tick):
    _inc = timedelta(1)
    _prefix = 'D'


class Hour(Tick):
    _inc = timedelta(0, 3600)
    _prefix = 'H'


class Minute(Tick):
    _inc = timedelta(0, 60)
    _prefix = 'T'


class Second(Tick):
    _inc = timedelta(0, 1)
    _prefix = 'S'


class Milli(Tick):
    _prefix = 'L'


class Micro(Tick):
    _inc = timedelta(microseconds=1)
    _prefix = 'U'


class Nano(Tick):
    _inc = np.timedelta64(1, 'ns')
    _prefix = 'N'


BDay = BusinessDay
BMonthEnd = BusinessMonthEnd
BMonthBegin = BusinessMonthBegin
CBMonthEnd = CustomBusinessMonthEnd
CBMonthBegin = CustomBusinessMonthBegin
CDay = CustomBusinessDay


def _get_firstbday(wkday):
    """
    wkday is the result of monthrange(year, month)

    If it's a saturday or sunday, increment first business day to reflect this
    """
    first = 1
    if wkday == 5:  # on Saturday
        first = 3
    elif wkday == 6:  # on Sunday
        first = 2
    return first


def generate_range(start=None, end=None, periods=None,
                   offset=BDay(), time_rule=None):
    """
    Generates a sequence of dates corresponding to the specified time
    offset. Similar to dateutil.rrule except uses pandas DateOffset
    objects to represent time increments

    Parameters
    ----------
    start : datetime (default None)
    end : datetime (default None)
    periods : int, optional
    time_rule : (legacy) name of DateOffset object to be used, optional
        Corresponds with names expected by tseries.frequencies.get_offset

    Notes
    -----
    * This method is faster for generating weekdays than dateutil.rrule
    * At least two of (start, end, periods) must be specified.
    * If both start and end are specified, the returned dates will
    satisfy start <= date <= end.
    * If both time_rule and offset are specified, time_rule supersedes offset.

    Returns
    -------
    dates : generator object

    """
    if time_rule is not None:
        from pandas.tseries.frequencies import get_offset

        offset = get_offset(time_rule)

    start = to_datetime(start)
    end = to_datetime(end)

    if start and not offset.onOffset(start):
        start = offset.rollforward(start)

    if end and not offset.onOffset(end):
        end = offset.rollback(end)

        if periods is None and end < start:
            end = None
            periods = 0

    if end is None:
        end = start + (periods - 1) * offset

    if start is None:
        start = end - (periods - 1) * offset

    cur = start

    next_date = cur
    while cur <= end:
        yield cur

        # faster than cur + offset
        next_date = offset.apply(cur)
        if next_date <= cur:
            raise ValueError('Offset %s did not increment date' % offset)
        cur = next_date

prefix_mapping = dict((offset._prefix, offset) for offset in [
    YearBegin,                # 'AS'
    YearEnd,                  # 'A'
    BYearBegin,               # 'BAS'
    BYearEnd,                 # 'BA'
    BusinessDay,              # 'B'
    BusinessMonthBegin,       # 'BMS'
    BusinessMonthEnd,         # 'BM'
    BQuarterEnd,              # 'BQ'
    BQuarterBegin,            # 'BQS'
    CustomBusinessDay,        # 'C'
    CustomBusinessMonthEnd,   # 'CBM'
    CustomBusinessMonthBegin, # 'CBMS'
    MonthEnd,                 # 'M'
    MonthBegin,               # 'MS'
    Week,                     # 'W'
    Second,                   # 'S'
    Minute,                   # 'T'
    Micro,                    # 'U'
    QuarterEnd,               # 'Q'
    QuarterBegin,             # 'QS'
    Milli,                    # 'L'
    Hour,                     # 'H'
    Day,                      # 'D'
    WeekOfMonth,              # 'WOM'
    FY5253,
    FY5253Quarter,
])

prefix_mapping['N'] = Nano


def _make_offset(key):
    """Gets offset based on key. KeyError if prefix is bad, ValueError if
    suffix is bad. All handled by `get_offset` in tseries/frequencies. Not
    public."""
    if key is None:
        return None
    split = key.replace('@', '-').split('-')
    klass = prefix_mapping[split[0]]
    # handles case where there's no suffix (and will TypeError if too many '-')
    obj = klass._from_name(*split[1:])
    obj._named = key
    return obj
