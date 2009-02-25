# Copyright (C) 2008 Valmantas Paliksa <walmis at balticum-tv dot lt>
# Copyright (C) 2008 Tadas Dailyda <tadas at dailyda dot com>
#
# Licensed under the GNU General Public License Version 3
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# 
import os
import gtk
import dbus
import gettext
import time
import atexit
import pickle
import base64
import gtk.gdk
import zlib
from blueman.main.Config import Config
from blueman.Functions import *
from blueman.main.Device import Device
from blueman.bluez.Device import Device as BluezDevice
from blueman.bluez.Adapter import Adapter
from blueman.main.SignalTracker import SignalTracker
import blueman.Sdp as sdp

_ = gettext.gettext

REGISTRY_VERSION = 0

def store_state():
	if RecentConns.items:
		items = []
		for i in RecentConns.items:
			x = i.copy()
			x["device"] = None
			x["mitem"] = None
			x["gsignal"] = 0
			items.append(x)

		
		dump = base64.b64encode(zlib.compress(pickle.dumps((REGISTRY_VERSION, items), pickle.HIGHEST_PROTOCOL), 9))
	
		c = Config()
		c.props.recent_connections = dump

atexit.register(store_state)

class RecentConns(gtk.Menu):
	
	items = None
	
	def __init__(self, applet):
		self.Item = applet.recent_item
		self.Applet = applet
		self.Signals = SignalTracker()
		self.Adapters = []
		gtk.Menu.__init__(self)
		
		
	def initialize(self):
		dprint("rebuilding menu")
		def compare_by (fieldname):
			def compare_two_dicts (a, b):
				return cmp(a[fieldname], b[fieldname])
			return compare_two_dicts
		
		def each(child):
			self.remove(child)
		self.foreach(each)

		RecentConns.items.sort(compare_by("time"), reverse=True)
		RecentConns.items = RecentConns.items[0:6]
		RecentConns.items.reverse()
		
		if len(RecentConns.items) == 0:
			self.Item.props.sensitive = False
		else:
			self.Item.props.sensitive = True

		count = 0
		for item in RecentConns.items:
			if count < 6:
				self.add_item(item)
				count+=1
	
	#set bluez manager interface
	def set_manager(self, manager):
		self.Manager = manager
		
		#get adapter paths, not objects
		adapters = self.Manager.ListAdapters()
		self.Adapters = {}
		for adapter in adapters:
			p = adapter.GetProperties()
			self.Adapters[str(adapter.GetObjectPath())] = str(p["Address"])
		
		
		self.Signals.DisconnectAll()
		self.Signals.Handle("bluez", self.Manager, self.on_adapter_added, "AdapterAdded")
		self.Signals.Handle("bluez", self.Manager, self.on_adapter_removed, "AdapterRemoved")
		
		if RecentConns.items != None:
			for i in reversed(RecentConns.items):
					
				if i["device"]:
					if i["gsignal"]:
						i["device"].disconnect(i["gsignal"])
					#i["device"].Destroy()
				
				try:
					i["device"] = self.get_device(i)
					i["gsignal"] = i["device"].connect("invalidated", self.on_device_removed, i)
				except:
					pass

		else:
			self.recover_state()
		
		self.initialize()
	
	def on_device_removed(self, device, item):
		device.disconnect(item["gsignal"])
		RecentConns.items.remove(item)
		self.initialize()
		
	def on_adapter_added(self, path):
		a = Adapter(path)
		def on_activated():
			props = a.GetProperties()
			self.Adapters[str(path)] = str(props["Address"])
			self.initialize()
		
		wait_for_adapter(a, on_activated)
		
	def on_adapter_removed(self, path):
		try:
			del self.Adapters[str(path)]
		except:
			dprint("Adapter not found in list")
		
		self.initialize()
		
	def notify(self, device, service_interface, conn_args):
		dprint(device, service_interface, conn_args)
		item = {}
		object_path = device.GetObjectPath()
		try:
			adapter = Adapter(device.Adapter)
		except:
			dprint("adapter not found")
			return
			
		props = adapter.GetProperties()
		
		item["adapter"] = props["Address"]
		item["address"] = device.Address
		item["alias"] = device.Alias
		item["icon"] = device.Icon
		item["service"] = service_interface
		item["conn_args"] = conn_args
		item["time"] = time.time()
		item["device"] = device #device object
		item["mitem"] = None #menu item object
		item["gsignal"] = item["device"].connect("invalidated", self.on_device_removed, item)
		
		for i in RecentConns.items:
			if i["adapter"] == item["adapter"] and \
			   i["address"] == item["address"] and \
			   i["service"] == item["service"] and \
			   i["conn_args"] == item["conn_args"]:
				i["time"] = item["time"]
				i["device"] = item["device"]
				self.initialize()
				return
		
		RecentConns.items.append(item)
		self.initialize()
		
		store_state()
		
	def on_item_activated(self, menu_item, item):
		dprint("Connect", item["address"], item["service"])
		
		sv_name = item["service"].split(".")[-1].lower()
		try:
			service = item["device"].Services[sv_name]
		except:
			RecentConns.items.remove(item)
		else:
			sn = startup_notification("Bluetooth Connection", desc=_("Connecting to %s") % item["mitem"].get_child().props.label, icon="blueman")
			
			
			def reply(*args):
				self.Applet.show_notification(_("Connected"), _("Connected to %s") % item["mitem"].get_child().props.label, pixbuf=get_icon("gtk-connect", 48))
				item["mitem"].props.sensitive = True
				sn.complete()
				
			def err(reason):
				self.Applet.show_notification(_("Failed to connect"), str(reason).split(": ")[-1], pixbuf=get_icon("gtk-dialog-error", 48))
				item["mitem"].props.sensitive = True
				sn.complete()

			if item["service"] == "org.bluez.Serial":
				self.Applet.DbusSvc.RfcommConnect(item["device"].GetObjectPath(), item["conn_args"][0], reply, err)
			else:
				service.Connect(reply_handler=reply, error_handler=err, *item["conn_args"])
			
			item["time"] = time.time()
			self.initialize()
			item["mitem"].props.sensitive = False
			
		
	def add_item(self, item):
		device = item["device"]
		
		if item["service"] == "org.bluez.Serial":
			name = sdp.uuid16_to_name(sdp.uuid128_to_uuid16(item["conn_args"][0]))
		elif item["service"] == "org.bluez.Network":
			name = _("Network Access (%s)") % sdp.uuid16_to_name(sdp.uuid128_to_uuid16(item["conn_args"][0]))
		else:
			name = item["service"].split(".")[-1] + " " + _("Service")
			name = name.capitalize()

		mitem = create_menuitem(_("%(service)s on %(device)s") % {"service":name, "device":item["alias"]}, get_icon(item["icon"], 16))
		item["mitem"] = mitem
		mitem.connect("activate", self.on_item_activated, item)

		if item["adapter"] not in self.Adapters.values():
			if item["device"] and item["gsignal"]:
				item["device"].disconnect(item["gsignal"])
			
			item["device"] = None
		elif not item["device"] and item["adapter"] in self.Adapters.values():
			try:
				dev = self.get_device(item)
				item["device"] = dev
				item["gsignal"] = item["device"].connect("invalidated", self.on_device_removed, item)
				
			except:
				RecentConns.items.remove(item)
				self.initialize()

		if not item["device"]:
			mitem.props.sensitive = False
			mitem.props.tooltip_text = _("Adapter for this connection is not available")
		
		
		self.prepend(mitem)
		mitem.show()
		
		
		
	def get_device(self, item):
		adapter = self.Manager.GetAdapter(item["adapter"])
		return Device(adapter.FindDevice(item["address"]))

		
		
	def recover_state(self):
		c = Config()
		dump = c.props.recent_connections
		try:
			(version, items) = pickle.loads(zlib.decompress(base64.b64decode(dump)))
		except:
			items = None
			version = None
		
		if version == None or version != REGISTRY_VERSION:
			items = None
		
		if items == None:
			RecentConns.items = []
			return
		
		for i in reversed(items):
			try:
				i["device"] = self.get_device(i)
			except Exception, e:
				print e
				i["device"] = None
			else:
				i["gsignal"] = i["device"].connect("invalidated", self.on_device_removed, i)
			
		RecentConns.items = items
		
