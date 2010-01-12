# -*- coding: utf-8 -*-
"""Recipe haproxy"""

import logging, os, shutil, tempfile, urllib2, urlparse
import setuptools.archive_util
import datetime
import sha
import sys
import shutil
import zc.buildout
import commands

def system(c):
    if os.system(c):
        raise SystemError("Failed", c)

# XXX Can I whack this? Seems evil, in that it's preventing me from doing 'target = generic'
# (in order to get haproxy to compile on Snow Leopard) by always forcing Makefile.osx.
#OSX = sys.platform.startswith('darwin')

class Recipe(object):
    """zc.buildout recipe"""

    def __init__(self, buildout, name, options):
        self.buildout, self.name, self.options = buildout, name, options
        directory = buildout['buildout']['directory']
        self.download_cache = buildout['buildout'].get('download-cache')
        self.install_from_cache = buildout['buildout'].get('install-from-cache')

        if self.download_cache:
            # cache keys are hashes of url, to ensure repeatability if the
            # downloads do not have a version number in the filename
            # cache key is a directory which contains the downloaded file
            # download details stored with each key as cache.ini
            self.download_cache = os.path.join(
                directory, self.download_cache, 'haproxy')

        # we assume that install_from_cache and download_cache values
        # are correctly set, and that the download_cache directory has
        # been created: this is done by the main zc.buildout anyway

        location = options.get(
            'location', buildout['buildout']['parts-directory'])
        options['location'] = os.path.join(location, name)
        options['prefix'] = options['location']

    def install(self):
        """Installer"""
        logger = logging.getLogger(self.name)
        dest = self.options['location']
        url = self.options['url']
        # TARGET=(linux22|linux24|linux24e|linux24eold|linux26|solaris|freebsd|openbsd|generic)
        target = self.options.get('target',None)
        # USE_PCRE=1
        pcre=self.options.get('pcre', None)
        # CPU=(i686|i586|ultrasparc|generic)
        cpu = self.options.get('cpu', None)
        extra_options = self.options.get('extra_options', '')
        # get rid of any newlines that may be in the options so they
        # do not get passed through to the commandline
        extra_options = ' '.join(extra_options.split())

        buildoptions = dict(PREFIX=dest, TARGET=target, USE_PCRE=pcre, CPU=cpu)

        fname = getFromCache(
            url, self.name, self.download_cache, self.install_from_cache)

        # now unpack and work as normal
        tmp = tempfile.mkdtemp('buildout-'+self.name)
        logger.info('Unpacking and configuring')
        setuptools.archive_util.unpack_archive(fname, tmp)

        here = os.getcwd()
        if not os.path.exists(dest):
            os.mkdir(dest)

        environ = self.options.get('environment', '').split()
        if environ:
            for entry in environ:
                logger.info('Updating environment: %s' % entry)
            environ = dict([x.split('=', 1) for x in environ])
            os.environ.update(environ)

        try:
            os.chdir(tmp)
            try:
                if not os.path.exists('Makefile'):
                    entries = os.listdir(tmp)
                    if len(entries) == 1:
                        os.chdir(entries[0])
                    else:
                        raise ValueError("Couldn't find Makefile")

#               XXX Potential evil? See my comment above.
#                if OSX:
#                    optionstring = ' '.join(['='.join(x) for x in buildoptions.items() if x[1] and x[0] not in ('CPU', 'TARGET')])
#                    system("make -f Makefile.osx %s %s" % (optionstring, extra_options))

                else:
                    optionstring = ' '.join(['='.join(x) for x in buildoptions.items() if x[1]])
                    system("make %s %s" % (optionstring, extra_options))
                system("make PREFIX=%s install" % dest)
            finally:
                os.chdir(here)
        except:
            shutil.rmtree(dest)
            raise

        # Add script wrappers
        bintarget=self.buildout["buildout"]["bin-directory"]

        for directory in ["bin", "sbin"]:
            fullpath = os.path.join(dest, directory)
            if not os.path.isdir(fullpath):
                continue
            for filename in os.listdir(fullpath):
                logger.info("Adding script wrapper for %s" % filename)
                target=os.path.join(bintarget, filename)
                f=open(target, "wt")
                print >>f, "#!/bin/sh"
                print >>f, 'exec %s "$@"' % os.path.join(fullpath, filename)
                f.close()
                os.chmod(target, 0755)
                self.options.created(target)

        return dest


    def update(self):
        """Updater"""
        pass

def getFromCache(url, name, download_cache=None, install_from_cache=False):
    if download_cache:
        cache_fname = sha.new(url).hexdigest()
        cache_name = os.path.join(download_cache, cache_fname)
        if not os.path.isdir(download_cache):
            os.mkdir(download_cache)

    _, _, urlpath, _, _ = urlparse.urlsplit(url)
    filename = urlpath.split('/')[-1]

    # get the file from the right place
    fname = tmp2 = None
    if download_cache:
        # if we have a cache, try and use it
        logging.getLogger(name).debug(
            'Searching cache at %s' % download_cache)
        if os.path.isdir(cache_name):
            # just cache files for now
            fname = os.path.join(cache_name, filename)
            logging.getLogger(name).debug(
                'Using cache file %s' % cache_name)

        else:
            logging.getLogger(name).debug(
                'Did not find %s under cache key %s' % (filename, cache_name))

    if not fname:
        if install_from_cache:
            # no file in the cache, but we are staying offline
            raise zc.buildout.UserError(
                "Offline mode: file from %s not found in the cache at %s" %
                (url, download_cache))
        try:
            # okay, we've got to download now
            # XXX: do we need to do something about permissions
            # XXX: in case the cache is shared across users?
            tmp2 = None
            if download_cache:
                # set up the cache and download into it
                os.mkdir(cache_name)
                fname = os.path.join(cache_name, filename)
                if filename != "cache.ini":
                    now = datetime.datetime.utcnow()
                    cache_ini = open(os.path.join(cache_name, "cache.ini"), "w")
                    print >>cache_ini, "[cache]"
                    print >>cache_ini, "download_url =", url
                    print >>cache_ini, "retrieved =", now.isoformat() + "Z"
                    cache_ini.close()
                logging.getLogger(name).debug(
                    'Cache download %s as %s' % (url, cache_name))
            else:
                # use tempfile
                tmp2 = tempfile.mkdtemp('buildout-' + name)
                fname = os.path.join(tmp2, filename)
                logging.getLogger(name).info('Downloading %s' % url)
            open(fname, 'w').write(urllib2.urlopen(url).read())
        except:
            if tmp2 is not None:
               shutil.rmtree(tmp2)
            if download_cache:
               shutil.rmtree(cache_name)
            raise

    return fname
