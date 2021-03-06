import json
import uuid
import os
import logging
import re
import base64
from typing import Dict, Union, Any, List, Iterable, Tuple
from datetime import datetime, date, time
from urllib.parse import quote
import requests

from Crypto.Cipher import AES
from CTUtil.types import DateSec
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from django.conf.urls import RegexURLPattern
from django.http import HttpRequest
import yaml
import pytz

logger_formatter = logging.Formatter(
    "%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s")
config_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'config')


def set_global_logging(logging_file: str = None,
                       logging_level: int = logging.INFO,
                       logging_config_file: Union[str, None] = None) -> None:
    import logging.config
    if not logging_config_file:
        config = dict(
            level=logging_level,
            format=
            "%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s"
        )
        if logging_file:
            config.update(filename=logging_file)
        logging.basicConfig(**config)
    else:
        if logging_config_file == 'default':
            logging_config_file = os.path.join(config_dir, 'logging.yaml')
        with open(logging_config_file, 'r') as f:
            config = yaml.load(f)
            logging.config.dictConfig(config)


def get_client_ip(request: HttpRequest):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_date_range(date: date) -> Tuple[datetime, datetime]:
    return datetime.combine(date, time.min), datetime.combine(date, time.max)


def queryset_paging(queryset: Iterable[Any], page: int, page_size: int):
    return queryset[(page - 1) * page_size:page * page_size]


def jstimestamp_to_datetime(jstimestamp: int,
                            tz: str = 'Asia/Shanghai',
                            use_tz: bool = False):
    if use_tz:
        return datetime.fromtimestamp(jstimestamp // 1000,
                                      tz=pytz.timezone(tz))
    else:
        return datetime.fromtimestamp(jstimestamp // 1000)


def get_django_all_url(urlpatterns: List[Any]):
    urls = []

    def search_url(src_urls: List[Any], root: str, pre_urls: List[str]):
        for url in src_urls:
            _root = os.path.join(root, url._regex).replace('^', '')
            if isinstance(url, RegexURLPattern):
                pre_urls.append(_root)
            else:
                search_url(url.url_patterns, _root, pre_urls)

    search_url(urlpatterns, '/', urls)
    return urls


def set_default_file_path(files_dir: str = 'image',
                          file_type: str = 'jpeg') -> str:
    _date: date = datetime.now().date()
    dir_path = os.path.join('static', files_dir, format(_date, '%Y%m%d'))
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    filename = f'{str(uuid.uuid4()).replace("-", "")}.{file_type}'
    path = os.path.join(dir_path, filename)
    return path


def process_base64_in_content(post: dict) -> None:
    content: str = post.setdefault('content', '')
    if not content:
        return
    search_base64 = re.search('\"data\:image\/(.*?)\;base64\,(.*?)\"', content)
    if not search_base64:
        return
    image_type = search_base64.group(1)
    image_base64_string = search_base64.group(2)
    image_decode = base64.b64decode(image_base64_string)
    file_path = set_default_file_path(file_type=image_type)
    with open(file_path, 'wb') as f:
        f.write(image_decode)
    content = content.replace(search_base64.group(),
                              '\"{path}\"'.format(path=file_path))
    post['content'] = content


def process_file_return_path(request,
                             files_name: str = 'file',
                             files_dir: str = 'image',
                             return_name: bool = False):
    _file = request.FILES.get(files_name)
    if not _file:
        if return_name:
            return None, None
        return
    file_type = (_file.name).split(".")[-1]
    file_path = set_default_file_path(file_type=file_type, files_dir=files_dir)
    with open(file_path, 'wb+') as f:
        for chunk in _file.chunks():
            f.write(chunk)
    path = file_path.replace('\\', '/')
    if return_name:
        return _file.name, path
    else:
        return path


def process_files_return_pathlist(request, files_dir: str = 'image'):
    myFiles = request.FILES
    data_list = []
    if myFiles:
        for myFile in myFiles.values():
            file_type = (myFile.name).split(".")[-1]
            file_path = set_default_file_path(file_type=file_type,
                                              files_dir=files_dir)
            with open(file_path, 'wb+') as f:
                for chunk in myFile.chunks():
                    f.write(chunk)
            data_list.append(file_path.replace('\\', '/'))
    return data_list


class TokenSerializer(object):

    def __init__(self, salt: str, overtime_sec: DateSec = DateSec.DAY):
        self.s = Serializer(salt, expires_in=overtime_sec)

    def encode(self, data: Any) -> bytes:
        return self.s.dumps(data)

    def decode(self, data: bytes) -> Any:
        return self.s.loads(data)


class WxLogin(object):
    # 网页端微信第三方登录接口
    def __init__(self, APPID, APPSECRET):
        self.appid = APPID
        self.secret = APPSECRET
        self.redirect_url = quote('https://www.cingta.com/')

    # 获取open_id
    def get_access_token(self, code):
        url = 'https://api.weixin.qq.com/sns/oauth2/access_token?appid={APPID}&secret={APPSECRET}&code={CODE}&grant_type=authorization_code'.format(
            APPID=self.appid,
            APPSECRET=self.secret,
            CODE=code,
        )
        resp = requests.get(url).json()
        return resp

    # 获取unionid
    @staticmethod
    def get_unionid(token, openid):
        url = 'https://api.weixin.qq.com/sns/userinfo?access_token={token}&openid={openid}'.format(
            token=token,
            openid=openid,
        )
        resp = requests.get(url).json()
        return resp.get('unionid')


class WXBizDataCrypt:
    # 微信小程序解码, 腾讯官方代码, 直接调用
    def __init__(self, appId, sessionKey):
        self.appId = appId
        self.sessionKey = sessionKey

    def decrypt(self, encryptedData, iv):
        sessionKey = base64.b64decode(self.sessionKey)
        encryptedData = base64.b64decode(encryptedData)
        iv = base64.b64decode(iv)

        cipher = AES.new(sessionKey, AES.MODE_CBC, iv)
        data = self._unpad(cipher.decrypt(encryptedData))
        decrypted = json.loads(data)

        if decrypted['watermark']['appid'] != self.appId:
            raise Exception('Invalid Buffer')

        return decrypted

    def _unpad(self, s):
        return s[:-ord(s[len(s) - 1:])]


class WxMiniInterface(object):
    # 微信小程序各种接口
    def __init__(self, APPID: str, APPSECRET: str):
        self.APPID = APPID
        self.APPSECRET = APPSECRET

    def get_user_session(self, code: str) -> Dict[str, str]:
        url = 'https://api.weixin.qq.com/sns/jscode2session?appid={AppID}&secret={AppSecret}&js_code={code}&grant_type=authorization_code'.format(
            AppID=self.APPID,
            AppSecret=self.APPSECRET,
            code=code,
        )
        resp = requests.get(url).json()
        return resp

    def get_user_info(self, session: str, encryptedata: str, iv: str) -> str:
        wx_mini = WXBizDataCrypt(self.APPID, session)
        userinfo = wx_mini.decrypt(encryptedata, iv)
        return userinfo

    def send_template_msg(self, **templatedata) -> Dict[str, str]:
        get_user_info = set(
            ['touser', 'template_id', 'page', 'form_id', 'data'])
        if not (get_user_info & set(templatedata.keys()) == get_user_info):
            raise TypeError(
                'send_template_msg missing required positional arguments: touser, template_id, page, form_id or data'
            )

        token_url: str = 'https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APPID}&secret={APPSECRET}'.format(
            APPID=self.APPID,
            APPSECRET=self.APPSECRET,
        )
        token: Dict[str, str] = requests.get(token_url).json()
        if token.get('errcode'):
            raise TypeError('error APPID or error APPSECRET')
        _token = token.get('access_token', '')
        template_url: str = 'https://api.weixin.qq.com/cgi-bin/message/wxopen/template/send?access_token={ACCESS_TOKEN}'.format(
            ACCESS_TOKEN=_token, )
        resp = requests.post(template_url,
                             data=json.dumps(templatedata)).json()
        return resp
