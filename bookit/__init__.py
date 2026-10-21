# PyMySQL is a pure-Python MySQL driver, so it installs on Windows without build tools.
try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:  # pragma: no cover
    pass
