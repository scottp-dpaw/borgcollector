import json
import logging
import traceback

from django import forms
from django.dispatch import receiver
from django.utils import timezone

from borg_utils.widgets import MultiWidgetLayout
from borg_utils.signals import refresh_select_choices
from django.core.cache import caches

logger = logging.getLogger(__name__)

try:
    shared_cache = caches["shared"]
except:
    logger.warning("Inter-process communication is disabled because redis cache is not configured properly.\n{0}".format(traceback.format_exc()))

class GroupedModelChoiceField(forms.ModelChoiceField):
    data_cache = {}
    def __init__(self, group, group_label=None,choice_family=None,choice_name=None, *args, **kwargs):
        """
        group_by_field is the name of a field on the model
        group_label is a function to return a label for each choice group
        """
        #import ipdb;ipdb.set_trace()
        self.choice_family = choice_family
        self.choice_name = choice_name
        if isinstance(group,basestring):
            self.group = lambda obj:getattr(obj,group,"")
        else:
            self.group = group
        if group_label is None:
            self.group_label = lambda group: str(group)
        else:
            self.group_label = group_label
        try:
            super(GroupedModelChoiceField, self).__init__(*args, **kwargs)
        except:
            pass

    def _get_choices(self):
        version = None
        choice_family = None
        #if self.choice_family == "workspace" and self.choice_name == "workspace_choices":
        #    import ipdb;ipdb.set_trace()
        if self.choice_family and self.choice_name :
            try:
                version = shared_cache.get(self.choice_family,None) if shared_cache else None
            except:
                version = None

            choice_family = GroupedModelChoiceField.data_cache.get(self.choice_family,None)
            if choice_family is None:
                #data is not cached, create one
                choice_family = {}
                GroupedModelChoiceField.data_cache[self.choice_family] = choice_family
        
            try:
                if choice_family:
                    if version:
                        if version == choice_family.get("version",None):
                            #same version,try to return the cached data if have
                            return choice_family[self.choice_name]
                        else:
                            #version is different,clear the data, and set the version to latest version
                            logger.info("The cache for {0} is cleared because version is different.".format(self.choice_family))
                            choice_family.clear()
                            choice_family["version"] = version
                    else:
                        #no new version,try to return the cached data if have
                        return choice_family[self.choice_name]
                else:
                    if version:
                        choice_family["version"] = version
            except:
                pass

        #required data is not cached, query data from database.
        #if cache is enabled, choice_family should be not none, otherwise,it is none.
        queryset = self.queryset.all()           
        if not queryset:
            return []
        all_choices = []
        if self.empty_label:
            current_optgroup = ""
            current_optgroup_choices = [("", self.empty_label)]
        else:
            current_optgroup = None
            current_optgroup_choices = None

        for item in queryset:
            optgroup_from_instance = self.group(item)
            if current_optgroup != optgroup_from_instance:
                if current_optgroup is not None:
                    all_choices.append((current_optgroup, current_optgroup_choices))
                current_optgroup_choices = []
                current_optgroup = optgroup_from_instance
            current_optgroup_choices.append((item.pk,self.group_label(item)))

        all_choices.append((current_optgroup, current_optgroup_choices))

        #try to cache the data, if can
        if choice_family is not None:
            choice_family[self.choice_name] = all_choices

        return all_choices

    choices = property(_get_choices, forms.ChoiceField._set_choices)


class SelectChoiceRefreshEventListener(object):

    @receiver(refresh_select_choices)
    def _refresh_select_choices(sender, **kwargs):
        try:
            if kwargs["choice_family"] in GroupedModelChoiceField.data_cache:
                del GroupedModelChoiceField.data_cache[kwargs["choice_family"]]

            if shared_cache:
                version = timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                shared_cache.set(kwargs["choice_family"],version,None)
        except:
            pass


class MetaTilingFactorWidget(MultiWidgetLayout):
    """
    A widget to configure meta tiling factor
    """
    def __init__(self):
        layout = [
            "tiles wide",forms.NumberInput(attrs={"min":1,"max":20,"style":"width:40px;margin:0px 10px 0px 10px"}),
            "by tiles high",forms.NumberInput(attrs={"min":1,"max":20,"style":"width:40px;margin:0px 10px 0px 10px"}),
        ]
        super(MetaTilingFactorWidget,self).__init__(layout)

    def decompress(self,value):
        if value:
            return value
        else:
            return [1,1]

class MetaTilingFactorField(forms.MultiValueField):
    """
    A field to configure meta tiling factor
    """
    def __init__(self,*args,**kwargs):
        fields=(
            forms.IntegerField(min_value=0,required=False),
            forms.IntegerField(min_value=0,required=False),
        )
        super(MetaTilingFactorField,self).__init__(fields=fields,widget=MetaTilingFactorWidget(),*args,**kwargs)

    def compress(self,data_list):
        if not data_list or len(data_list) != 2:
            return [1,1]
        else:
            return data_list
        
class GridSetWidget(MultiWidgetLayout):
    """
    A widget to configure a grid set for cached layer
    """
    def __init__(self):
        layout = [
            "<b>Enable:</b>",forms.CheckboxInput(attrs={"style":"width:40px;margin:0px 30px 0px 5px"}),
            "<em><b>Published Zoom Level:</b></em>",forms.NumberInput(attrs={"min":0,"max":32,"style":"width:40px;margin:0px 10px 0px 10px"}),
            "To",forms.NumberInput(attrs={"min":0,"max":32,"style":"width:40px;margin:0px 50px 0px 10px"}),
            "<em><b>Cached Zoom Level:</b></em>",forms.NumberInput(attrs={"min":0,"max":32,"style":"width:40px;margin:0px 10px 0px 10px"}),
            "To",forms.NumberInput(attrs={"min":0,"max":32,"style":"width:40px;margin:0px 10px 0px 10px"}),
        ]
        super(GridSetWidget,self).__init__(layout)

    def decompress(self,value):
        if value:
            try:
                v = [value.get('enabled',False),None,None,None,None]
                v[1] = value.get('min_zoom_level',None)
                v[2] = value.get('max_zoom_level',None)
                v[3] = value.get('min_cache_level',None)
                v[4] = value.get('max_cache_level',None)
                return v
            except:
                return [False,None,None,None,None]
        else:
            return [False,None,None,None,None]

class GridSetField(forms.MultiValueField):
    """
    A field to configure a grid set for cached layer
    """
    def __init__(self,*args,**kwargs):
        fields=(
            forms.BooleanField(required=False),
            forms.IntegerField(min_value=0,required=False),
            forms.IntegerField(min_value=0,required=False),
            forms.IntegerField(min_value=0,required=False),
            forms.IntegerField(min_value=0,required=False),
        )
        super(GridSetField,self).__init__(fields=fields,widget=GridSetWidget(),required=False,*args,**kwargs)

    def compress(self,data_list):
        if data_list:
            try:
                d = {'enabled':data_list[0]}
                if len(data_list) >= 2 and data_list[1] and data_list[1] >= 0: d['min_zoom_level'] = data_list[1]

                if len(data_list) >= 3 and data_list[2] and data_list[2] >=0: 
                    if d.get('min_zoom_level') and d.get('min_zoom_level') > data_list[2]:
                        raise ValidationError('max_zoom_level should be equal or larger than min_zoon_level')
                    d['max_zoom_level'] = data_list[2]

                if len(data_list) >= 4 and data_list[3] and data_list[3] >=0: 
                    if d.get('min_zoom_level') and d.get('min_zoom_level') > data_list[3]:
                        raise ValidationError('min_cache_level should be equal or larger than min_zoon_level')
                    d['min_cache_level'] = data_list[3]

                if len(data_list) >= 5 and data_list[4] and data_list[4] >=0: 
                    if d.get('min_cache_level') and d.get('min_cache_level') > data_list[4]:
                        raise ValidationError('max_cache_level should be equal or larger than min_cache_level')
                    if d.get('max_zoom_level') and d.get('max_zoom_level') < data_list[4]:
                        raise ValidationError('max_cache_level should be equal or less than max_zoom_level')
                    d['max_cache_level'] = data_list[4]
                return d
            except ValidationError:
                raise
            except:
                return None
        else:
            return None


class GeoserverSettingForm(object):
    """
    A form which contain geoserver setting fields
    """

    def get_setting_from_model(self, *args, **kwargs):
        if 'instance' in kwargs and  kwargs['instance']:
            #populate the geoserver settings form fields value from table data
            if kwargs['instance'].geoserver_setting:
                geoserver_setting = json.loads(kwargs['instance'].geoserver_setting)
                json_key = None
                for name,field in type(self).base_fields.items():
                    if not hasattr(field,"setting_type") or getattr(field,"setting_type") != "geoserver_setting": continue
                    json_key = field.key if hasattr(field,"key") else field.label
                    if hasattr(field,"group"):
                        if field.group in geoserver_setting and json_key in geoserver_setting[field.group]:
                             kwargs['initial'][name] = geoserver_setting[field.group][json_key]
                        else:
                             kwargs['initial'][name] = None
                    else:
                        if json_key in geoserver_setting:
                             kwargs['initial'][name] = geoserver_setting[json_key]
                        else:
                             kwargs['initial'][name] = None

        

    def set_setting_to_model(self):
        #populate the geoserver settings table data from form field data.
        geoserver_setting = {}
        json_key = None
        for name,field in self.fields.items():
            if not hasattr(field,"setting_type") or getattr(field,"setting_type") != "geoserver_setting": continue
            json_key = field.key if hasattr(field,"key") else field.label
            if name in self.cleaned_data :
                if hasattr(field,"group"):
                    if field.group not in geoserver_setting:
                        geoserver_setting[field.group] = {}
                    geoserver_setting[field.group][json_key] = self.cleaned_data[name]
                else:
                    geoserver_setting[json_key] = self.cleaned_data[name]
        if geoserver_setting:
            self.instance.geoserver_setting = json.dumps(geoserver_setting)
        else:
            self.instance.geoserver_setting = None


