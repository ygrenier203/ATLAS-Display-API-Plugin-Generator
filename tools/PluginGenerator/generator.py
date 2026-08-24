import argparse
import os


def run(args=None):
	parser = argparse.ArgumentParser(description='Generate an ATLAS display plugin.')
	parser.add_argument('name', nargs='?', help='plugin name; omit to open the GUI')
	parser.add_argument('--output', help='parent folder for the generated plugin; required until configured')
	parser.add_argument('--library-project', help='path to DisplayPluginLibrary.csproj; required for parameter plugins until configured')
	parser.add_argument('--icon', help='path to the plugin PNG icon; required until configured')
	parser.add_argument('--no-view', action='store_true', help='omit the WPF view files')
	parser.add_argument('--no-parameters', action='store_true', help='omit dynamic parameter support')
	parser.add_argument('--max-parameters', type=int, default=100, help='maximum number of display parameters')
	parser.add_argument('--clear-settings', action='store_true', help='clear persisted paths used by the generator and exit')
	options = parser.parse_args(args)

	from .gui import clear_settings, default_output_folder, default_workspace_root, generate_plugin, load_settings, main, save_settings

	if options.clear_settings:
		clear_settings()
		print('Persisted generator settings cleared.')
		return

	if not options.name:
		main()
		return

	settings = load_settings()
	output = options.output or settings.get('output_folder') or default_output_folder()
	library_project = options.library_project or settings.get('library_project', '')
	icon_path = options.icon or settings.get('icon_path', '')
	if not output:
		parser.error('--output is required on first use. Choose the parent folder for the generated plugin.')
	if not options.no_parameters and not library_project:
		parser.error('--library-project is required for parameter plugins on first use.')
	if not icon_path:
		parser.error('--icon is required on first use. Choose the PNG icon for the plugin.')
	target = generate_plugin(
		options.name,
		output,
		include_view=not options.no_view,
		include_parameters=not options.no_parameters,
		parameter_max_count=options.max_parameters,
		workspace_root=default_workspace_root(),
		library_project=library_project,
		icon_path=icon_path,
	)
	save_settings({
		'output_folder': output,
		'library_project': library_project,
		'icon_path': icon_path,
	})
	print(f'Plugin created at: {target}')


if __name__ == '__main__':
	run()
