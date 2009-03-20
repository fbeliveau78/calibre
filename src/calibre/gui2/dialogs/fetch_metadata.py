__license__   = 'GPL v3'
__copyright__ = '2008, Kovid Goyal <kovid at kovidgoyal.net>'
'''
GUI for fetching metadata from servers.
'''

import time

from PyQt4.QtCore import Qt, QObject, SIGNAL, QVariant, QThread, \
                         QAbstractTableModel, QCoreApplication, QTimer
from PyQt4.QtGui import QDialog, QItemSelectionModel, QWidget, QLabel, QMovie

from calibre.gui2.dialogs.fetch_metadata_ui import Ui_FetchMetadata
from calibre.gui2 import error_dialog, NONE, info_dialog, warning_dialog
from calibre.utils.config import prefs

class Fetcher(QThread):
    
    def __init__(self, title, author, publisher, isbn, key):
        QThread.__init__(self)
        self.title = title
        self.author = author
        self.publisher = publisher
        self.isbn = isbn
        self.key = key
        
    def run(self):
        from calibre.ebooks.metadata.fetch import search
        self.results, self.exceptions = search(self.title, self.author,
                                               self.publisher, self.isbn, 
                                               self.key if self.key else None)

class ProgressIndicator(QWidget):
    
    def __init__(self, *args):
        QWidget.__init__(self, *args)
        self.setGeometry(0, 0, 300, 350)
        self.movie = QMovie(':/images/jobs-animated.mng')
        self.ml = QLabel(self)
        self.ml.setMovie(self.movie)
        self.movie.start()
        self.movie.setPaused(True)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignHCenter|Qt.AlignTop)
        self.status.font().setBold(True)
        self.status.font().setPointSize(self.font().pointSize()+6)
        self.setVisible(False)
        
    def start(self, msg=''):
        view = self.parent()
        pwidth, pheight = view.size().width(), view.size().height()
        self.resize(pwidth, min(pheight, 250))
        self.move(0, (pheight-self.size().height())/2.)
        self.ml.resize(self.ml.sizeHint())
        self.ml.move(int((self.size().width()-self.ml.size().width())/2.), 0)
        self.status.resize(self.size().width(), self.size().height()-self.ml.size().height()-10)
        self.status.move(0, self.ml.size().height()+10)
        self.status.setText(msg)
        self.setVisible(True)
        self.movie.setPaused(False)
        
    def stop(self):
        if self.movie.state() == self.movie.Running:
            self.movie.setPaused(True)
            self.setVisible(False)
            
class Matches(QAbstractTableModel):
    
    def __init__(self, matches):
        self.matches = matches
        self.matches.sort(cmp=lambda b, a: \
                        cmp(len(a.comments if a.comments else ''), 
                            len(b.comments if b.comments else '')))
        QAbstractTableModel.__init__(self)
        
    def rowCount(self, *args):
        return len(self.matches)
    
    def columnCount(self, *args):
        return 5
    
    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return NONE
        text = ""
        if orientation == Qt.Horizontal:      
            if   section == 0: text = _("Title")
            elif section == 1: text = _("Author(s)")
            elif section == 2: text = _("Author Sort")
            elif section == 3: text = _("Publisher")
            elif section == 4: text = _("ISBN")
            
            return QVariant(text)
        else: 
            return QVariant(section+1)
        
    def summary(self, row):
        return self.matches[row].comments
    
    def data(self, index, role):
        row, col = index.row(), index.column()
        if role == Qt.DisplayRole:
            book = self.matches[row]
            res = None
            if col == 0:
                res = book.title
            elif col == 1:
                res = ', '.join(book.authors)
            elif col == 2:
                res = book.author_sort
            elif col == 3:
                res = book.publisher
            elif col == 4:
                res = book.isbn
            if not res:
                return NONE
            return QVariant(res)
        return NONE

class FetchMetadata(QDialog, Ui_FetchMetadata):
    
    def __init__(self, parent, isbn, title, author, publisher, timeout):
        QDialog.__init__(self, parent)
        Ui_FetchMetadata.__init__(self)
        self.setupUi(self)
        
        self.pi = ProgressIndicator(self)
        self.timeout = timeout
        QObject.connect(self.fetch, SIGNAL('clicked()'), self.fetch_metadata)
        
        self.key.setText(prefs['isbndb_com_key'])
        
        self.setWindowTitle(title if title else _('Unknown'))
        self.isbn = isbn
        self.title = title
        self.author = author.strip()
        self.publisher = publisher
        self.previous_row = None
        self.connect(self.matches, SIGNAL('activated(QModelIndex)'), self.chosen)
        self.connect(self.matches, SIGNAL('entered(QModelIndex)'), 
                     lambda index:self.matches.setCurrentIndex(index))
        self.matches.setMouseTracking(True)
        self.fetch_metadata()
        
        
    def show_summary(self, current, previous):
        row  = current.row()
        if row != self.previous_row:
            summ =  self.model.summary(row)
            self.summary.setText(summ if summ else '')
            self.previous_row = row
        
    def fetch_metadata(self):
        key = str(self.key.text())
        if key:
            prefs['isbndb_com_key'] =  key
        else:
            key = None
        title = author = publisher = isbn = None
        if self.isbn:
            isbn = self.isbn
        if self.title:
            title = self.title
        if self.author and not self.author == _('Unknown'):
            author = self.author
        self.fetch.setEnabled(False)
        self.setCursor(Qt.WaitCursor)
        QCoreApplication.instance().processEvents()
        self.fetcher = Fetcher(title, author, publisher, isbn, key)
        self.fetcher.start()
        self.pi.start(_('Finding metadata...'))
        self._hangcheck = QTimer(self)
        self.connect(self._hangcheck, SIGNAL('timeout()'), self.hangcheck)
        self.start_time = time.time()
        self._hangcheck.start()
        
    def hangcheck(self):
        if not (self.fetcher.isFinished() or time.time() - self.start_time > 75):
            return
        self._hangcheck.stop()
        try:
            if self.fetcher.isRunning():
                error_dialog(self, _('Could not find metadata'),
                             _('The metadata download seems to have stalled. '
                               'Try again later.')).exec_()
                self.fetcher.terminate()
                return
            self.model = Matches(self.fetcher.results)
            warnings = [(x[0], unicode(x[1])) for x in \
                            self.fetcher.exceptions if x[1] is not None]
            if warnings:
                warnings='<br>'.join(['<b>%s</b>: %s'%(name, exc) for name,exc in warnings])
                warning_dialog(self, _('Warning'),
                               '<p>'+_('Could not fetch metadata from:')+\
                               '<br><br>'+warnings+'</p>').exec_()
            if self.model.rowCount() < 1:
                info_dialog(self, _('No metadata found'),
                     _('No metadata found, try adjusting the title and author '
                       'or the ISBN key.')).exec_()
                self.reject()
                return
            
            self.matches.setModel(self.model)
            QObject.connect(self.matches.selectionModel(), 
                        SIGNAL('currentRowChanged(QModelIndex, QModelIndex)'),
                        self.show_summary)
            self.model.reset()
            self.matches.selectionModel().select(self.model.index(0, 0), 
                                  QItemSelectionModel.Select | QItemSelectionModel.Rows)
            self.matches.setCurrentIndex(self.model.index(0, 0))
        finally:
            self.fetch.setEnabled(True)
            self.unsetCursor()
            self.matches.resizeColumnsToContents()
            self.pi.stop()
            
        
    def selected_book(self):
        try:
            return self.matches.model().matches[self.matches.currentIndex().row()]
        except:
            return None
        
    def chosen(self, index):
        self.matches.setCurrentIndex(index)
        self.accept()
