import React, { useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, X, Search, BookOpen, Folder } from 'lucide-react';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type { Skill, SkillListItem, SkillCreate, SkillUpdate, CategoryListResponse } from '../types';

interface SkillFormData {
  name: string;
  category: string;
  description: string;
  content: string;
}

const initialFormData: SkillFormData = {
  name: '',
  category: '',
  description: '',
  content: '',
};

export const SkillsPage: React.FC = () => {
  const [skills, setSkills] = useState<SkillListItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Skill[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillListItem | null>(null);
  const [viewingSkill, setViewingSkill] = useState<Skill | null>(null);
  const [formData, setFormData] = useState<SkillFormData>(initialFormData);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [skillsData, categoriesData] = await Promise.all([
          api.getSkills(selectedCategory || undefined),
          api.getCategories(),
        ]);
        setSkills(skillsData.items);
        setCategories(categoriesData.categories);
      } catch (err) {
        setError('Failed to load skills');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [selectedCategory]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }

    setIsSearching(true);
    try {
      const results = await api.searchSkills(searchQuery);
      setSearchResults(results.items);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setIsSearching(false);
    }
  };

  const handleOpenModal = (skill?: SkillListItem) => {
    if (skill) {
      setEditingSkill(skill);
      // Fetch full skill data for editing
      api.getSkill(skill.name).then((fullSkill) => {
        setFormData({
          name: fullSkill.name,
          category: fullSkill.category,
          description: fullSkill.description,
          content: fullSkill.content || '',
        });
      });
    } else {
      setEditingSkill(null);
      setFormData(initialFormData);
    }
    setShowModal(true);
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setEditingSkill(null);
    setFormData(initialFormData);
  };

  const handleViewSkill = async (skillName: string) => {
    try {
      const skill = await api.getSkill(skillName);
      setViewingSkill(skill);
      setShowViewModal(true);
    } catch (err) {
      alert('Failed to load skill content');
      console.error(err);
    }
  };

  const handleCloseViewModal = () => {
    setShowViewModal(false);
    setViewingSkill(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);

    try {
      if (editingSkill) {
        // Update existing skill
        const updateData: SkillUpdate = {
          description: formData.description,
          content: formData.content,
        };
        await api.updateSkill(editingSkill.name, updateData);
      } else {
        // Create new skill
        const createData: SkillCreate = {
          name: formData.name,
          category: formData.category,
          description: formData.description,
          content: formData.content,
        };
        await api.createSkill(createData);
      }

      // Refresh skills list
      const skillsData = await api.getSkills(selectedCategory || undefined);
      setSkills(skillsData.items);
      const categoriesData = await api.getCategories();
      setCategories(categoriesData.categories);
      handleCloseModal();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to save skill');
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (skillName: string, isBuiltin: boolean) => {
    if (isBuiltin) {
      alert('Builtin skills cannot be deleted');
      return;
    }

    if (!confirm(`Are you sure you want to delete skill "${skillName}"?`)) return;

    try {
      await api.deleteSkill(skillName);
      const skillsData = await api.getSkills(selectedCategory || undefined);
      setSkills(skillsData.items);
      const categoriesData = await api.getCategories();
      setCategories(categoriesData.categories);
    } catch (err) {
      alert('Failed to delete skill');
      console.error(err);
    }
  };

  // Group skills by category
  const groupedSkills = skills.reduce((acc, skill) => {
    if (!acc[skill.category]) {
      acc[skill.category] = [];
    }
    acc[skill.category].push(skill);
    return acc;
  }, {} as Record<string, SkillListItem[]>);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Skills</h2>
        <button
          onClick={() => handleOpenModal()}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Create Skill
        </button>
      </div>

      {/* Search Bar */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search skills..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={isSearching}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {isSearching ? 'Searching...' : 'Search'}
          </button>
        </div>

        {/* Search Results */}
        {searchResults.length > 0 && (
          <div className="mt-4 border-t pt-4">
            <h3 className="text-sm font-medium text-gray-700 mb-2">
              Search Results ({searchResults.length})
            </h3>
            <div className="space-y-2">
              {searchResults.map((skill) => (
                <div
                  key={skill.name}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900">{skill.name}</span>
                      <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded-full">
                        {skill.category}
                      </span>
                      {skill.is_builtin && (
                        <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-800 rounded-full">
                          Builtin
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-1">{skill.description}</p>
                  </div>
                  <button
                    onClick={() => handleViewSkill(skill.name)}
                    className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg"
                    title="View"
                  >
                    <BookOpen className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Category Filter */}
      {categories.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-gray-500">Filter by category:</span>
          <button
            onClick={() => setSelectedCategory(null)}
            className={`px-3 py-1 text-sm rounded-full transition-colors ${
              selectedCategory === null
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            All
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1 text-sm rounded-full transition-colors ${
                selectedCategory === cat
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      {/* Skills Grid by Category */}
      <div className="space-y-6">
        {Object.entries(groupedSkills).map(([category, categorySkills]) => (
          <div key={category} className="bg-white rounded-lg shadow">
            <div className="px-4 py-3 border-b flex items-center gap-2">
              <Folder className="w-4 h-4 text-gray-400" />
              <h3 className="font-medium text-gray-900">{category}</h3>
              <span className="text-sm text-gray-500">({categorySkills.length})</span>
            </div>
            <div className="divide-y">
              {categorySkills.map((skill) => (
                <div
                  key={skill.name}
                  className="px-4 py-3 flex items-center justify-between hover:bg-gray-50"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900">{skill.name}</span>
                      {skill.is_builtin && (
                        <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-800 rounded-full">
                          Builtin
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-1">{skill.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleViewSkill(skill.name)}
                      className="p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg"
                      title="View"
                    >
                      <BookOpen className="w-4 h-4" />
                    </button>
                    {!skill.is_builtin && (
                      <>
                        <button
                          onClick={() => handleOpenModal(skill)}
                          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
                          title="Edit"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(skill.name, skill.is_builtin)}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        {skills.length === 0 && !selectedCategory && (
          <div className="bg-white rounded-lg shadow p-6 text-center text-gray-500">
            No skills yet. Click "Create Skill" to add one.
          </div>
        )}

        {skills.length === 0 && selectedCategory && (
          <div className="bg-white rounded-lg shadow p-6 text-center text-gray-500">
            No skills in category "{selectedCategory}".
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">
                {editingSkill ? 'Edit Skill' : 'Create Skill'}
              </h3>
              <button
                onClick={handleCloseModal}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="p-4 space-y-4 flex-1 overflow-y-auto">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    disabled={!!editingSkill}
                    required
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-100"
                    placeholder="e.g., git_clone"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Category
                  </label>
                  <input
                    type="text"
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    disabled={!!editingSkill}
                    required
                    list="categories"
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-100"
                    placeholder="e.g., git, shell, web"
                  />
                  <datalist id="categories">
                    {categories.map((cat) => (
                      <option key={cat} value={cat} />
                    ))}
                  </datalist>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  required
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                  placeholder="Brief description of what this skill does"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Content (Markdown)
                </label>
                <textarea
                  value={formData.content}
                  onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                  required
                  rows={15}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 font-mono text-sm"
                  placeholder="# Skill Title&#10;&#10;## When to Use&#10;When you need to...&#10;&#10;## Procedures&#10;1. Step one&#10;2. Step two"
                />
              </div>

              <div className="flex justify-end gap-2 pt-4 border-t">
                <button
                  type="button"
                  onClick={handleCloseModal}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {submitting ? 'Saving...' : editingSkill ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* View Modal */}
      {showViewModal && viewingSkill && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-medium">{viewingSkill.name}</h3>
                <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded-full">
                  {viewingSkill.category}
                </span>
                {viewingSkill.is_builtin && (
                  <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-800 rounded-full">
                    Builtin
                  </span>
                )}
              </div>
              <button
                onClick={handleCloseViewModal}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto flex-1">
              <p className="text-gray-600 mb-4">{viewingSkill.description}</p>
              <pre className="whitespace-pre-wrap text-sm bg-gray-50 p-4 rounded-lg overflow-x-auto">
                {viewingSkill.content || 'No content'}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SkillsPage;
