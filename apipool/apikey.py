#!/usr/bin/env python
# -*- coding: utf-8 -*-

import inspect


class ApiKey(object):
    """
    API key abstract class.

    User has to implement these three methods to make it works.

    - :meth:`ApiKey.get_primary_key`.
    - :meth:`ApiKey.create_client`.
    - :meth:`ApiKey.test_usability`.
    """

    _client = None
    _apikey_manager = None

    def get_primary_key(self):
        """
        Get the unique identifier of this api key. Usually it is a string or
        integer. For example, the AWS Access Key is the primary key of an
        aws api key pair.

        :return: str or int.
        """

        raise NotImplementedError

    def create_client(self):
        """
        Create a client object to perform api call.

        This method will use api key data to create a client class.

        For example, if you use `geopy <https://geopy.readthedocs.io/en/stable/>`_,
        and you want to use Google Geocoding API, then

        .. code-block:: python

            >>> from geopy.geocoders import GoogleV3
            >>> class YourApiKey(ApiKey):
            ...     def __init__(self, apikey):
            ...         self.apikey = apikey
            ...
            ...     def create_client(self):
            ...         return GoogleV3(api_key=self.apikey)

        api for ``geopy.geocoder.GoogleV3``: https://geopy.readthedocs.io/en/stable/#googlev3

        :return: client object.
        """
        raise NotImplementedError

    def test_usability(self, client):
        """
        Test if this api key is usable for making api call.

        Usually this method is just to make a simple, guarantee successful
        api call, and then check the response.

        :return: bool, or raise Exception
        """
        raise NotImplementedError

    @property
    def primary_key(self):
        return self.get_primary_key()

    def connect_client(self):
        """
        connect
        :return:
        """
        self._client = self.create_client()

    async def aconnect_client(self):
        """Async version of connect_client.

        If ``create_client`` is a coroutine function, it will be awaited.
        Otherwise, it falls back to the synchronous ``create_client``.
        """
        if inspect.iscoroutinefunction(self.create_client):
            self._client = await self.create_client()
        else:
            self._client = self.create_client()

    def is_usable(self):
        if self._client is None:
            self.connect_client()
        try:
            return self.test_usability(self._client)
        except:  # pragma: no cover
            return False

    async def ais_usable(self):
        """Async version of is_usable.

        Ensures the client is connected (using aconnect_client if needed),
        then calls test_usability. If test_usability is a coroutine function,
        it will be awaited.
        """
        if self._client is None:
            await self.aconnect_client()
        try:
            result = self.test_usability(self._client)
            if inspect.isawaitable(result):
                return await result
            return result
        except:  # pragma: no cover
            return False
