# WriteControl

A Vim plugin that tracks your writing sessions, providing detailed analytics on your editing patterns, productivity, and writing habits.

## Features

* Tracks keystroke patterns and editing behavior
* Records time spent in different Vim modes (Normal, Insert, Visual)
* Generates detailed analytics on writing sessions
* Maintains session history with writing speed and productivity metrics
* Integrates with Git for file tracking across repositories
* Respects XDG directory specifications

## Installation

### Using [Vim-Plug](https://github.com/junegunn/vim-plug)
```vim
Plug 'theinvertedform/vim-writecontrol'
```

```vim
Plugin 'theinvertedform/vim-writecontrol'
```

```bash
git clone https://github.com/theinvertedform/vim-writecontrol.git ~/.vim/bundle/writecontrol
```

```bash
git clone https://github.com/yourusername/writecontrol.git
cd writecontrol
# Copy files to their respective locations
mkdir -p ~/.vim/plugin
cp plugin/writecontrol.vim ~/.vim/plugin/
cp -r bin/* ~/.local/bin/
```

## Requirements

* Vim 8.1+ with Python 3 support (`:echo has('python3')` should return 1)
* Python 3.6 or newer
* Optional: Git (for enhanced file tracking across repositories)

## Configuration

Add any of these settings to your `.vimrc` to customize WriteControl:

```vim
" Enable debug mode for detailed logging
let g:writecontrol_debug = 1
```

## Usage

WriteControl automatically starts tracking when you open a file in Vim.

### Commands

- `:StartTracking` - Manually start a tracking session
- `:StopTracking` - Manually end a tracking session
- `:ToggleWriteControlDebug` - Toggle debug mode

### Analytics

View session reports with the included analytics tool:

```bash
# Show summary for a specific file
wc-analytics.py summary --filename myfile.txt

# Process log files
wc-analytics.py process /path/to/logs/*.json

# List all tracked projects
wc-analytics.py list --sort words
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
