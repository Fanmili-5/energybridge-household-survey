# This is only an official SDK format conversion. No schedules are generated.
require 'openstudio'

model = OpenStudio::Model::Model.load(OpenStudio::Path.new(ARGV.fetch(0)))
raise 'Source OSM could not be loaded' if model.empty?

translator = OpenStudio::EnergyPlus::ForwardTranslator.new
workspace = translator.translateModel(model.get)
raise 'Source forward translation failed' unless workspace.save(OpenStudio::Path.new(ARGV.fetch(1)), false)
