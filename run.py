"""
PyChanEditor Copyright (C) 2014 Karsten Bock

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""

import os
import sys
import argparse


def main():
    """Creates the application and runs it"""
    parser = argparse.ArgumentParser(description='PyChanEditor')
    parser.add_argument('--fife_path', type=str, default=None,
                       help='the path to the fife module')
    args = parser.parse_args()
    if args.fife_path:
        sys.path.insert(0, args.fife_path)
    from fife import fife
    print ("Using the FIFE python module found here: ",
            os.path.dirname(fife.__file__))

    from fife.extensions.fife_settings import Setting

    from editor.application import EditorApplication

    settings = Setting(app_name="PyChanEditor", settings_file="./settings.xml")

    app = EditorApplication(settings)
    app.run()

if __name__ == '__main__':
    main()
