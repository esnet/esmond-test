from django.db import models
from django.utils.timezone import now
import datetime

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from esmond.util import datetime_to_unixtime, remove_metachars, max_datetime, atencode

class DeviceTag(models.Model):
    """A tag for a :py:class:`.Device.`"""

    name = models.CharField(max_length = 256, unique=True)

    class Meta:
        db_table = "devicetag"

    def __unicode__(self):
        return self.name

class DeviceManager(models.Manager):
    def active(self):
        qs = super(DeviceManager, self).get_query_set()
        qs = qs.filter(active=True, end_time__gt=now())
        return qs

    def active_as_dict(self):
        d = {}

        for dev in self.active():
            d[dev.name] = dev

        return d

class Device(models.Model):
    """A system which is pollable via SNMP.

    Referred to as a Managed Device in SNMP terminology.

    """
    name = models.CharField(max_length = 256)
    begin_time = models.DateTimeField()
    end_time = models.DateTimeField(default=max_datetime)
    community = models.CharField(max_length = 128)
    active = models.BooleanField(default = True)
    devicetag = models.ManyToManyField(DeviceTag, through = "DeviceTagMap")
    oidsets = models.ManyToManyField("OIDSet", through = "DeviceOIDSetMap")

    objects = DeviceManager()

    class Meta:
        db_table = "device"
        ordering = ['name']

    def __unicode__(self):
        return self.name

    def to_dict(self):
        return dict(
                begin_time=datetime_to_unixtime(self.begin_time),
                end_time=datetime_to_unixtime(self.end_time),
                name=self.name,
                active=self.active)


class DeviceTagMap(models.Model):
    """Associates a set of :py:class:`.DeviceTag`s with a :py:class:`.Device`"""

    device = models.ForeignKey(Device, db_column="deviceid")
    device_tag = models.ForeignKey(DeviceTag, db_column="devicetagid")

    class Meta:
        db_table = "devicetagmap"

class OIDType(models.Model):
    """Defines the type for an :py:class:`.OID`"""

    name = models.CharField(max_length=256)
    class Meta:
        db_table = "oidtype"
        ordering = ["name"]

    def __unicode__(self):
        return self.name

class Poller(models.Model):
    """Defines a Poller that can be used to collect data."""

    name = models.CharField(max_length=256)

    class Meta:
        db_table = "poller"
        ordering = ["name"]

    def __unicode__(self):
        return self.name

class OID(models.Model):
    """An Object Identifier.  

    This is a variable that can be measured via SNMP.

    """

    name = models.CharField(max_length=256)
    aggregate = models.BooleanField(default = False)
    oid_type = models.ForeignKey(OIDType,db_column = "oidtypeid")
    endpoint_alias = models.CharField(max_length=256, null=True, blank=True,
        help_text="Optional endpoint alias (in, out, discard/out, etc)")

    class Meta:
        db_table = "oid"
        ordering = ["name"]

    def __unicode__(self):
        return self.name

class OIDSet(models.Model):
    """A collection of :py:class:`.OID`s that are collected together."""

    name = models.CharField(max_length=256, help_text="Name for OIDSet.")
    frequency = models.IntegerField(help_text="Polling frequency in seconds.")
    poller = models.ForeignKey(Poller,db_column="pollerid", 
        help_text="Which poller to use for this OIDSet")
    poller_args = models.CharField(max_length=256, null=True, blank=True,
        help_text="Arguments for the Poller")
    oids = models.ManyToManyField(OID, through = "OIDSetMember", 
            help_text="List of OIDs in the OIDSet")

    class Meta:
        db_table = "oidset"
        ordering = ["name"]

    def __unicode__(self):
        return self.name

    @property
    def aggregates(self):
        aggs = []
        if self.poller_args:
            for i in self.poller_args.split(" "):
                k,v = i.split("=")
                if k == "aggregates":
                    aggs = map(int, v.split(","))
                    break
        return aggs

    @property
    def ttl(self):
        ttl = None
        if self.poller_args:
            for i in self.poller_args.split(" "):
                k,v = i.split("=")
                if k == "ttl":
                    ttl = int(v)
                    break
        return ttl

    @property
    def frequency_ms(self):
        return self.frequency * 1000

    @property
    def set_name(self):
        set_name = self.name
        if self.poller_args:
            for i in self.poller_args.split(" "):
                k, v = i.split("=")
                if k == "set_name":
                    set_name = v
                    break

        return set_name
    
class OIDSetMember(models.Model):
    """Associate :py:class:`.OID`s with :py:class:`.OIDSets`"""

    oid = models.ForeignKey(OID,db_column="oidid")
    oid_set = models.ForeignKey(OIDSet,db_column="oidsetid")

    class Meta:
        db_table = "oidsetmember"
        ordering = ["oid_set", "oid"]

class DeviceOIDSetMap(models.Model):
    """Associate :py:class:`.OIDSet`s with :py:class:`.Device`s"""

    device = models.ForeignKey(Device,db_column="deviceid")
    oid_set = models.ForeignKey(OIDSet,db_column="oidsetid")

    class Meta:
        db_table = "deviceoidsetmap"
        ordering = ["device", "oid_set"]

class IfRefManager(models.Manager):
    def active(self):
        qs = super(IfRefManager, self).get_query_set()
        qs = qs.filter(end_time__gt=now())
        return qs

class IfRef(models.Model):
    """Interface metadata.

    Data is stored with a begin_time and end_time.  A new row is only created
    when one or more columns change.  This provides a historical view of the
    interface metadata.
    
    """

    device = models.ForeignKey(Device, db_column="deviceid")
    ifIndex = models.IntegerField(db_column="ifindex")
    ifDescr = models.CharField(max_length=512, db_column="ifdescr")
    ifAlias = models.CharField(max_length=512, db_column="ifalias", blank=True,
            null=True)
    ipAddr = models.IPAddressField(blank=True, db_column="ipaddr", null=True)
    ifSpeed = models.BigIntegerField(db_column="ifspeed", blank=True, null=True)
    ifHighSpeed = models.BigIntegerField(db_column="ifhighspeed", blank=True,
            null=True)
    ifMtu = models.IntegerField(db_column="ifmtu", blank=True, null=True)
    ifType = models.IntegerField(db_column="iftype", blank=True, null=True)
    ifOperStatus = models.IntegerField(db_column="ifoperstatus",
            blank=True, null=True)
    ifAdminStatus = models.IntegerField(db_column="ifadminstatus",
            blank=True, null=True)
    begin_time = models.DateTimeField()
    end_time = models.DateTimeField(default=max_datetime)
    ifPhysAddress = models.CharField(max_length=32, db_column="ifphysaddress",
            blank=True, null=True)

    objects = IfRefManager()

    class Meta:
        db_table = "ifref"
        ordering = ["device__name", "ifDescr"]
        permissions = (
                ("can_see_hidden_ifref",
                    "Can see IfRefs with ifAlias containing :hide:"),
                )

    def __unicode__(self):
        return "%s (%s) %s"%(self.ifDescr, self.ifIndex, self.ifAlias)

    def encoded_ifDescr(self):
        return atencode(self.ifDescr)

    def to_dict(self):

        if not self.ifHighSpeed or self.ifHighSpeed == 0:
            speed = self.ifSpeed
        else:
            speed = self.ifHighSpeed * int(1e6)

        return dict(name=self.ifDescr,
                    descr=self.ifAlias,
                    speed=speed, 
                    begin_time=datetime_to_unixtime(self.begin_time),
                    end_time=datetime_to_unixtime(self.end_time),
                    device=self.device.name,
                    ifIndex=self.ifIndex,
                    ifDescr=self.ifDescr,
                    ifAlias=self.ifAlias,
                    ifSpeed=self.ifSpeed,
                    ifHighSpeed=self.ifHighSpeed,
                    ipAddr=self.ipAddr)

class ALUSAPRefManager(models.Manager):
    def active(self):
        qs = super(ALUSAPRefManager, self).get_query_set()
        qs = qs.filter(end_time__gt=now())
        return qs

class ALUSAPRef(models.Model):
    """Metadata about ALU SAPs."""

    device = models.ForeignKey(Device, db_column="deviceid")
    name = models.CharField(max_length=128)
    sapDescription = models.CharField(max_length=512,
            db_column="sapdescription")
    sapIngressQosPolicyId = models.IntegerField(
            db_column="sapingressqospolicyid")
    sapEgressQosPolicyId = models.IntegerField(
            db_column="sapegressqospolicyid")

    begin_time = models.DateTimeField()
    end_time = models.DateTimeField(default=max_datetime)

    objects = ALUSAPRefManager()

    class Meta:
        db_table = "alusapref"
        ordering = ["device__name", "name"]

    def __unicode__(self):
        return "%s %s" % (self.device, self.name)

    def to_dict(self):
        return dict(name=self.name,
                device=self.device.name,
                sapDescription=self.sapDescription,
                sapEgressQosPolicyId=self.sapEgressQosPolicyId,
                sapIngressQosPolicyId=self.sapIngressQosPolicyId,
                end_time=datetime_to_unixtime(self.end_time),
                begin_time=datetime_to_unixtime(self.begin_time))

class HistoryTableManager(models.Manager):
    def active(self):
        qs = super(HistoryTableManager, self).get_query_set()
        qs = qs.filter(end_time__gt=now())
        return qs

class OutletRef(models.Model):
    device = models.ForeignKey(Device, db_column="deviceid")
    outletID = models.CharField(max_length=128)
    outletName = models.CharField(max_length=128)
    outletStatus = models.IntegerField()
    outletControlState = models.IntegerField(blank=True, null=True)

    begin_time = models.DateTimeField()
    end_time = models.DateTimeField(default=max_datetime)
    
    objects = HistoryTableManager()

    class Meta:
        db_table = "outletref"
        ordering = ["device__name", "outletID"]

    def __unicode__(self):
        return "%s %s: %s" % (self.device, self.outletID, self.outletName)

    def to_dict(self):
        return dict(device=self.device.name, 
                    outletID=self.outletID,
                    outletName=self.outletName,
                    outletStatus=self.outletStatus,
                    outletControlState=self.outletControlState)

class LSPOpStatus(models.Model):
    """Metadata about MPLS LSPs."""
    device = models.ForeignKey(Device, db_column="deviceid")
    name = models.CharField(max_length=128)
    srcAddr = models.IPAddressField()
    dstAddr = models.IPAddressField()
    state = models.IntegerField()

    begin_time = models.DateTimeField()
    end_time = models.DateTimeField(default=max_datetime)

    class Meta:
        db_table = "lspopstatus"
        ordering = ["device__name", "name"]

    def __unicode__(self):
        return "%s %s" % (self.device, self.name)

class APIPermissionManager(models.Manager):
    def get_query_set(self):
        return super(APIPermissionManager, self).\
            get_query_set().filter(content_type__name='api_permission')


class APIPermission(Permission):
    """A global permission, not attached to a model"""

    objects = APIPermissionManager()

    class Meta:
        proxy = True
        permissions = (
            ("esmond_api.view_timeseries", "View timseries data"),
            ("esmond_api.add_timeseries", "Add timseries data"),
            ("esmond_api.delete_timeseries", "Delete timseries data"),
            ("esmond_api.change_timeseries", "Change timseries data"),
        )

    def save(self, *args, **kwargs):
        ct, created = ContentType.objects.get_or_create(
            name="api_permission", app_label=self._meta.app_label
        )
        self.content_type = ct
        super(APIPermission, self).save(*args, **kwargs)

### Models for data inventory

class Inventory(models.Model):
    """Data inventory to drive gap scanning"""
    # choices for cf to scan
    RAW_DATA = 'RD'
    BASE_RATES = 'BR'
    RATE_AGGS = 'RA'
    STAT_AGGS = 'SA'
    COLUMN_FAMILY_CHOICES = (
        (RAW_DATA, 'raw_data'),
        (BASE_RATES, 'base_rates'),
        (RATE_AGGS, 'rate_aggregations'),
        (STAT_AGGS, 'stat_aggregations')
    )
    # fields
    row_key = models.CharField(max_length=128, unique=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    last_scan_point = models.DateTimeField(null=True, blank=True)
    scan_complete = models.BooleanField(default=False)
    column_family = models.CharField(max_length=2, 
                                    choices=COLUMN_FAMILY_CHOICES,
                                    default=BASE_RATES)

    class Meta:
        db_table = 'inventory'
        ordering = ['row_key']

    def __unicode__(self):
        return self.row_key

    def to_dict(self):
        return dict(
            row_key=self.row_key,
            last_scan_point=self.last_scan_point,
            scan_complete=self.scan_complete
        )

class GapInventory(models.Model):
    """Inventory of gaps existing in the data"""
    row = models.ForeignKey(Inventory, db_column='keyid')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    processed = models.BooleanField(default=False)

    class Meta:
        db_table = 'gap_inventory'
        ordering = ['row__row_key']

    def __unicode__(self):
        return self.row.row_key

    def to_dict(self):
        return dict(
            row=self.row.row_key,
            processed=self.processed
        )
